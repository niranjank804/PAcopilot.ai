import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.tools.base import Tool, truncate_code
from src.core.exceptions import PermissionDeniedException
from src.repositories.auth_repository import auth_repository


class SearchKnowledgeBaseTool(Tool):

    name = "search_knowledge_base"
    description = (
        "Search the organization's knowledge base — uploaded TI scripts, "
        "rules, feeders, naming conventions, design standards and "
        "documentation — for guidance relevant to the current task. Returns "
        "the most relevant excerpts with their source filenames. Call this "
        "BEFORE drafting any TurboIntegrator process, rule or feeder so the "
        "generated code follows the organization's own standards, and cite "
        "which standard you applied."
    )
    required_permission = "knowledge.read"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "What to look up, for example 'TI process naming "
                    "convention', 'rule and feeder writing standard', or "
                    "'dimension naming rules'."
                ),
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        **kwargs,
    ) -> str:

        if not await auth_repository.user_has_permission(
            db, user_id, self.required_permission
        ):
            raise PermissionDeniedException(
                "You do not have permission to read the knowledge base."
            )

        # Imported lazily: src.knowledge.service imports the AI orchestrator,
        # which imports this tool registry at module load — a top-level import
        # here would create a circular import.
        from src.knowledge import retrieval
        from src.knowledge.exceptions import KnowledgeServiceError
        from src.knowledge.service import knowledge_service

        query = str(kwargs["query"])

        try:
            # top_k is deliberately generous: reference TI/rule files are
            # split across several chunks, and returning more per call lets an
            # agent reconstruct a full standard in one search instead of many
            # — which otherwise burns tool rounds before it can draft.
            matches = await knowledge_service.search(
                db, organization_id=organization_id, query=query, top_k=10
            )
        except KnowledgeServiceError as exc:
            # No longer the embeddings path — an unavailable embedding
            # provider now degrades to keyword search instead of raising,
            # and that case is handled below via `degraded`. Kept for any
            # other way retrieval can fail outright, because a
            # code-generation request must not abort over a failed
            # standards lookup.
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "note": (
                        f"Knowledge base search is unavailable ({exc.message}). "
                        "Tell the user the organization's standards could not "
                        "be checked, then proceed using standard TM1 practice."
                    ),
                }
            )

        # Degraded retrieval has to reach the agent, not just the UI.
        # This tool answers "what are our standards?" for a model about
        # to draft production TurboIntegrator, so the difference between
        # "nothing matched" and "nothing matched, using word search" is
        # the difference between a safe default and a false negative the
        # agent states with confidence.
        degraded = getattr(matches, "mode", retrieval.SEMANTIC) == retrieval.KEYWORD

        if not matches:
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "note": (
                        "No matching standards were found by keyword search, "
                        "and semantic search is currently unavailable — a "
                        "standard phrased differently would not have matched. "
                        "Tell the user this could not be checked properly, "
                        "then apply sensible TM1 defaults."
                        if degraded
                        else "No matching standards were found in the knowledge "
                        "base. Tell the user that no organizational standard "
                        "was found for this, then apply sensible TM1 defaults."
                    ),
                }
            )

        results = [
            {
                "source": match.chunk.document.filename,
                "chunk": match.chunk.chunk_index,
                "content": truncate_code(match.chunk.content, 3000),
            }
            for match in matches
        ]

        payload = {"query": query, "results": results}

        if degraded:
            payload["note"] = (
                "Found by keyword search — semantic search is unavailable, so "
                "these share words with the query rather than meaning, and "
                "other relevant standards may have been missed. Treat as "
                "incomplete and say so."
            )

        return json.dumps(payload)
