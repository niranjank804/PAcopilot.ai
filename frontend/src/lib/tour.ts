"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The product tour's data and state, separate from how it is drawn.
 *
 * Steps are declarative and target `data-tour` attributes rather than
 * class names or DOM positions. Classes here are Tailwind utilities
 * that change whenever someone restyles a card, and coordinates are
 * wrong the moment a viewport differs — a tour pinned to either breaks
 * silently, pointing at nothing while still looking like it works.
 *
 * A step whose target is absent is **skipped, not faked**. That is what
 * makes the tour safe to run for every role: a Viewer has no Users
 * page, so the element is not in their DOM and the step does not exist
 * for them. Nothing here needs its own copy of the permission rules,
 * which would be a second place for them to drift from the backend's.
 */

export interface TourStep {
  /** Matches `data-tour="..."` on the element to highlight. */
  target: string;
  title: string;
  body: string;
  /** Navigate here first. Omitted when the target is always present. */
  route?: string;
}

/**
 * The global tour: what the product is, in the order a new user meets
 * it. Every step points at something that exists today — no roadmap
 * entries, and nothing the capability registry marks PLANNED.
 */
export const PRODUCT_TOUR: TourStep[] = [
  {
    target: "nav-dashboard",
    route: "/dashboard",
    title: "Command Center",
    body: "Everything that needs attention on the servers you can use: model health and its biggest risks, open incidents and alerts, failed and slow processes, changes waiting for approval, recent deployments and AI cost.",
  },
  {
    target: "nav-chat",
    route: "/dashboard",
    title: "AI Assistant",
    body: "Ask about cubes, rules, processes or errors in plain English. Pick a specialist agent and it reads your live model with TM1 tools; any change it drafts waits for a person to review.",
  },
  {
    target: "voice-input",
    route: "/chat",
    title: "Or ask out loud",
    body: "Dictate a question instead of typing it. The transcript lands in the box for you to check before sending — and follows exactly the same permission and approval rules.",
  },
  {
    target: "nav-visualize",
    route: "/dashboard",
    title: "Visualize",
    body: "Turn a question into an MDX query and a chart from live cube data. Change the chart type, axis, legend, sort and number format, and export the view to CSV, Excel or an image. Read-only.",
  },
  {
    target: "nav-knowledge",
    route: "/dashboard",
    title: "Knowledge Base",
    body: "Upload your own documentation so answers cite your material rather than generic TM1 advice. Explain Error lives here too: paste a TM1 error and get the cause and the fix.",
  },
  {
    target: "nav-team",
    route: "/dashboard",
    title: "Team",
    body: "Work items with their whole story — investigation, root cause, fix, approval and deployment — plus incidents, the conversations colleagues shared with you, and what changed on your servers.",
  },
  {
    target: "nav-memory",
    route: "/dashboard",
    title: "Engineering Memory",
    body: "What your team knows that TM1 cannot say: run sequences, conventions, cautions and known issues. Approved entries reach the assistant in every conversation; its own suggestions wait for approval.",
  },
  {
    target: "nav-connections",
    route: "/dashboard",
    title: "Connections",
    body: "Register a TM1 or Planning Analytics server. Credentials are encrypted before they are stored, the connection is scoped to your organization, and Test tells you which part is wrong if it cannot connect.",
  },
  {
    target: "nav-metadata",
    route: "/dashboard",
    title: "Metadata Explorer",
    body: "Browse cubes, dimensions, processes and chores, and walk the dependency graph — including what a change to an object would affect.",
  },
  {
    target: "nav-deployments",
    route: "/dashboard",
    title: "Nothing is written without you",
    body: "AI-drafted rule, process and cell changes wait here as drafts with their impact analysis. A person reviews and executes; the assistant never writes to TM1 on its own, and the previous version is kept for rollback.",
  },
  {
    target: "nav-health",
    route: "/dashboard",
    title: "Model Health",
    body: "A health score for the model with the evidence behind every point, plus how long processes take: regressions, the slowest loads and recent failures.",
  },
  {
    target: "nav-reports",
    route: "/dashboard",
    title: "Reports",
    body: "Developer preview: refresh PAfE workbooks on a schedule through a Windows worker you run. Workers and Executions sit underneath once you open it.",
  },
  {
    target: "nav-alerts",
    route: "/dashboard",
    title: "Alerts",
    body: "Rules that watch your servers — failed or slow processes, dimension growth, security, model and deployment changes — and the alerts they raise. Rules only read TM1.",
  },
  {
    target: "alerts-bell",
    route: "/dashboard",
    title: "Open alerts at a glance",
    body: "The bell counts open alerts and turns red when one is critical. Click it to go straight to them.",
  },
  {
    target: "nav-monitoring",
    route: "/dashboard",
    title: "Monitoring",
    body: "AI usage by model, every TM1 tool call with its error rate, and the circuit-breaker state of each connection.",
  },
  {
    target: "nav-users",
    route: "/dashboard",
    title: "Users",
    body: "Everyone in your organization, their role, and whether they are active. Roles decide who can review and deploy changes.",
  },
  {
    target: "nav-settings",
    route: "/dashboard",
    title: "Settings",
    body: "Your organization's details and plan.",
  },
  {
    target: "nav-platform",
    route: "/dashboard",
    title: "Platform (Super Admin)",
    body: "Everyone across every workspace: sign-ins with time and address, TM1 connections and the TM1 user each uses (never a password), who used which server and on what, and the audit log — with deactivate, sign-out and suspend to stop misuse.",
  },
  {
    target: "page-tour",
    route: "/dashboard",
    title: "A tour for every page",
    body: "Each page has its own Take a tour button here, which walks through every option on that page.",
  },
  {
    target: "demo-button",
    route: "/dashboard",
    title: "Watch the demo",
    body: "Short replays of real workflows on a sample model — diagnosing a rule, drafting a fix, charting a question, correcting a value, investigating an incident and more — so you can see one before trying it on your own server.",
  },
  {
    target: "help-menu",
    route: "/dashboard",
    title: "Restart this any time",
    body: "This tour lives under Help. That is also where you will find it again after you finish.",
  },
];

/** Where the highlighted element sits, in viewport coordinates — the
 * overlay that draws it is `position: fixed`. */
export interface Spotlight {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function measure(target: string): Spotlight | null {
  const element = document.querySelector(`[data-tour="${target}"]`);

  if (!element) return null;

  const rect = element.getBoundingClientRect();

  // A zero-size box means the element is in the DOM but not laid out —
  // a collapsed sidebar on mobile, or a node inside a closed section.
  // Highlighting it would draw a marker over nothing.
  if (rect.width === 0 && rect.height === 0) return null;

  // Viewport coordinates, exactly as getBoundingClientRect gives them.
  // Adding window.scrollY here put the spotlight 22px below the
  // microphone whenever the document scrolled by 22px: the overlay is
  // fixed, so it already moves with the viewport, and the scroll offset
  // was being applied twice.
  return {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  };
}

/** How long a step waits for its element after a navigation before it
 * is skipped: long enough for a page to load its data, short enough that
 * a missing element does not look like a hang. */
const WAIT_FOR_TARGET_MS = 2500;
const POLL_MS = 150;

export function useTour(steps: TourStep[] = PRODUCT_TOUR) {
  // The steps this run will show: fixed when it starts, so the count in
  // "Step 3 of 7" matches what the user will actually see.
  const [active, setActive] = useState<TourStep[]>(steps);
  const [index, setIndex] = useState<number | null>(null);
  const [spotlight, setSpotlight] = useState<Spotlight | null>(null);
  const direction = useRef<1 | -1>(1);

  const isRunning = index !== null;
  const step = isRunning ? (active[index] ?? null) : null;

  const start = useCallback(() => {
    // Steps on this screen must be here now; one that is absent (an
    // option this role or state does not show) is left out rather than
    // shown pointing at nothing. Steps on another screen are kept and
    // checked once the tour has navigated there.
    const here = window.location.pathname;
    const shown = steps.filter(
      (candidate) =>
        (candidate.route && candidate.route !== here) || measure(candidate.target),
    );
    direction.current = 1;
    setActive(shown);
    setSpotlight(null);
    setIndex(shown.length ? 0 : null);
  }, [steps]);

  const stop = useCallback(() => {
    setIndex(null);
    setSpotlight(null);
  }, []);

  const next = useCallback(() => {
    direction.current = 1;
    setIndex((current) => {
      if (current === null) return null;
      return current + 1 >= active.length ? null : current + 1;
    });
  }, [active.length]);

  const back = useCallback(() => {
    direction.current = -1;
    setIndex((current) => (current === null ? null : Math.max(0, current - 1)));
  }, []);

  // Re-measure on scroll and resize: the popover is positioned from the
  // element's real box, so a tour that measured once would drift away
  // from its target the moment anything moved.
  useEffect(() => {
    if (!step || index === null) return;

    let frame = 0;
    let waited = 0;
    let poll: ReturnType<typeof setInterval> | undefined;

    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setSpotlight(measure(step.target)));
    };

    // An element that is not there yet may still be loading after a
    // navigation; one that never appears is skipped in the direction the
    // user was going, never shown pointing at an empty screen.
    const found = measure(step.target);
    update();
    if (!found) {
      poll = setInterval(() => {
        const box = measure(step.target);
        waited += POLL_MS;
        if (box) {
          clearInterval(poll);
          document
            .querySelector(`[data-tour="${step.target}"]`)
            ?.scrollIntoView({ block: "center", behavior: "smooth" });
          setSpotlight(box);
        } else if (waited >= WAIT_FOR_TARGET_MS) {
          clearInterval(poll);
          const target = index + direction.current;
          if (target < 0) {
            direction.current = 1;
            setIndex(index + 1 < active.length ? index + 1 : null);
          } else {
            setIndex(target < active.length ? target : null);
          }
        }
      }, POLL_MS);
    } else {
      document
        .querySelector(`[data-tour="${step.target}"]`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(frame);
      if (poll) clearInterval(poll);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [step, index, active.length]);

  return {
    isRunning,
    index,
    step,
    steps: active,
    // Nothing is drawn until the target is found, so the card never
    // floats over a screen with nothing highlighted.
    ready: spotlight !== null,
    spotlight,
    start,
    stop,
    next,
    back,
  };
}

/**
 * Per-feature tours, keyed by the route they belong to.
 *
 * Same engine, same skip-if-absent rule — so a step whose element a
 * given role or state does not render simply drops out. That is why
 * these can name the Review panel on Deployments without checking
 * whether a change is selected: with nothing selected the panel is not
 * in the DOM, and the step is not shown.
 *
 * Every page has one, and together they cover every option on it.
 * Related controls share a step so a tour stays short enough to finish.
 */
export const FEATURE_TOURS: Record<string, TourStep[]> = {
  "/platform": [
    {
      target: "platform-overview",
      title: "The platform at a glance",
      body: "Workspaces, people and those waiting for approval, who was active and signed in over the last day (with failed attempts), TM1 connections and how many are suspended, and AI requests and cost.",
    },
    {
      target: "platform-search",
      title: "Find anyone or anything",
      body: "Filters every tab at once: names, emails, workspaces, server names and addresses, TM1 users and IP addresses.",
    },
    {
      target: "platform-tabs",
      title: "Four views",
      body: "People, TM1 connections, Sign-ins and the Audit log. Each lists every workspace, newest or most recently active first.",
    },
    {
      target: "platform-people",
      title: "People",
      body: "Each person's workspace and roles, status, last sign-in, last activity, the address they last signed in from, how many TM1 servers they used and own in 30 days, and their AI requests and cost.",
    },
    {
      target: "platform-person-actions",
      title: "Activity, sign out, deactivate",
      body: "The clock shows what they did in 30 days — each action, every TM1 call the assistant made for them with the server and objects touched — and their sign-ins. Sign out ends every session; Deactivate also blocks sign-in until you reactivate. Your reason goes into the audit log.",
    },
    {
      target: "platform-connections",
      title: "TM1 connections",
      body: "Every server each workspace connected: address and port, database and tenant for cloud servers, the TM1 user it signs in as, environment, owner, when it was last used and by whom. Passwords and API keys are never shown.",
    },
    {
      target: "platform-connection-actions",
      title: "Suspend a connection",
      body: "Stops every use of its credentials — chat, alerts, deployments, scheduled jobs — until you resume it. Its owner sees that it is suspended and your reason.",
    },
    {
      target: "platform-sign-ins",
      title: "Sign-ins",
      body: "Every attempt with its time, result, method, address and device, including failures for names that match no account — what a password-guessing run looks like.",
    },
    {
      target: "platform-audit",
      title: "Audit log",
      body: "Every recorded action across all workspaces with who, where from and on which server. Export CSV saves it for a review or an incident.",
    },
  ],
  "/dashboard": [
    {
      target: "dashboard-ask",
      title: "Ask PA Copilot",
      body: "Opens the AI assistant, where you can ask about cubes, rules, TurboIntegrator processes or errors in plain English.",
    },
    {
      target: "dashboard-kpis",
      title: "Last 30 days at a glance",
      body: "AI runs across your organization, the share of TM1 tool calls that succeeded, how many failed, and tokens used with an estimated cost and cached share. A low success rate usually means a connection is down or metadata has not been extracted.",
    },
    {
      target: "dashboard-setup",
      title: "Connect a server first",
      body: "The command center fills in once a TM1 server is connected on the Connections page. It then shows model health, failures, approvals and deployments here.",
    },
    {
      target: "dashboard-health",
      title: "Model health",
      body: "The latest health score and grade for each server you can use, lowest first. The count is servers scoring under 75, and the biggest model risks underneath show how many points each costs. Click the title to open Health.",
    },
    {
      target: "dashboard-incidents",
      title: "Active incidents",
      body: "Incidents that are open or in progress, with their reference and severity. Click one to open it on the Team page.",
    },
    {
      target: "dashboard-alerts",
      title: "Open alerts",
      body: "Alerts raised by your monitoring rules, latest first. The count turns red when any of them is critical.",
    },
    {
      target: "dashboard-failures",
      title: "Failed processes",
      body: "Processes that failed in the last 7 days, read from TM1's message log, with how many times and when they last failed.",
    },
    {
      target: "dashboard-regressions",
      title: "Performance regressions",
      body: "Process runs that took far longer than they usually do, so you can catch a slowdown before it becomes a failure.",
    },
    {
      target: "dashboard-approvals",
      title: "Waiting for approval",
      body: "Valid drafted changes that nobody has applied yet, tagged with their environment. Click one to review it in Deployments.",
    },
    {
      target: "dashboard-deployments",
      title: "Recent deployments and model changes",
      body: "Changes executed or rolled back in the last 14 days, with status and who did it, plus model changes detected on each server, such as objects added or removed.",
    },
    {
      target: "dashboard-ai-usage",
      title: "AI usage and cost",
      body: "How many answers the assistant gave your organization, their estimated cost and the average answer time. The title opens Monitoring for the detail.",
    },
    {
      target: "dashboard-recent",
      title: "Recent AI activity",
      body: "Your six latest assistant sessions, newest first. Click one to pick the conversation up where you left it.",
    },
    {
      target: "dashboard-connections",
      title: "TM1 connections",
      body: "Each connection's circuit-breaker state: healthy, recovering or unavailable, with recent failure counts. If any are not answering normally, a link to Monitoring appears below.",
    },
  ],

  "/visualize": [
    {
      target: "visualize-question",
      title: "Ask a data question",
      body: "Describe the data you want in plain language and pick the TM1 connection to read from. Naming the measure and period gives the best result. Up to 2,000 cells come back.",
    },
    {
      target: "visualize-examples",
      title: "Example questions",
      body: "Click one to drop it into the question box as a starting point, then edit it to match your model.",
    },
    {
      target: "visualize-run",
      title: "Visualize",
      body: "The Analyst agent finds the cube, confirms real element names and writes and tests the MDX. Most questions take under a minute, a large cube can take a few, and the page waits.",
    },
    {
      target: "visualize-mdx",
      title: "The MDX behind the chart",
      body: "This is the query that produced the result. Edit MDX lets you change it and Run query sends it straight to TM1 with no AI and no quota; MDX only reads, so it cannot change data.",
    },
    {
      target: "chart-visual",
      title: "Visual",
      body: "Choose from 13 views: column, bar, stacked and 100% stacked columns, line, area, pie, donut, treemap, heatmap, waterfall, KPI cards or a matrix. Every change re-pivots the same result in your browser, without asking again.",
    },
    {
      target: "chart-axis",
      title: "Axis",
      body: "The dimension whose members run along the chart's categories. Picking a new axis clears any slicer on that dimension.",
    },
    {
      target: "chart-legend",
      title: "Legend",
      body: "Splits each category into one series per member of another dimension, or None for a single series. Pie, donut, treemap, waterfall and KPI cards show one number per category, so they have no legend.",
    },
    {
      target: "chart-slicer",
      title: "Slicers",
      body: "Every other dimension with more than one member gets a slicer. Leave it on All (summed) or pick one member to filter the chart to it.",
    },
    {
      target: "chart-sort",
      title: "Sort and Show",
      body: "Sort orders the categories as returned, largest first, smallest first or A to Z. Show, next to it, keeps only the top 5, 10, 20 or 50.",
    },
    {
      target: "chart-numbers",
      title: "Numbers and Size",
      body: "Numbers sets the format: full (1,234.5), compact (1.2K), thousands, millions or percent of total. Size, next to it, makes the chart small, medium or large.",
    },
    {
      target: "chart-toggles",
      title: "Data labels, Legend, Gridlines",
      body: "Turn value labels, the legend and gridlines on or off. They appear only on drawn charts, and only where they apply to the chosen visual.",
    },
    {
      target: "chart-exports",
      title: "Export",
      body: "Export view saves the chart's pivoted numbers as you see them; Export all cells saves every cell the query returned. Each comes as CSV or Excel, and Save image downloads drawn charts as a PNG.",
    },
    {
      target: "chart-table",
      title: "Table view",
      body: "Expand to see the numbers behind the chart as a table with row and column totals. It is hidden when Matrix is the chosen visual, because that already is the table.",
    },
  ],

  "/knowledge": [
    {
      target: "knowledge-upload",
      title: "Upload a document",
      body: "Add your organization's TM1 documentation as PDF, DOCX, TXT or Markdown so answers can be grounded in it. Uploading needs write access to the knowledge base.",
    },
    {
      target: "knowledge-documents",
      title: "Your documents",
      body: "Each upload shows whether it is still processing, completed or failed, with the reason for a failure. The bin icon deletes a document and its indexed content after you confirm; this cannot be undone.",
    },
    {
      target: "knowledge-ask",
      title: "Ask your documents",
      body: "Type a question and press Ask. The answer lists the document passages it used under Sources, and warns you if it had to fall back to keyword matching instead of meaning.",
    },
    {
      target: "knowledge-agent",
      title: "Documents only, or an agent",
      body: "Leave this on Documents only to answer from your uploads alone, or pick a specialist agent to also use live TM1 tools in the same answer. Either way it usually takes 20 to 40 seconds.",
    },
    {
      target: "knowledge-answer",
      title: "The answer",
      body: "The answer, the model and tokens used, and the document chunks it cited. If nothing matched, it says no matching document content was found.",
    },
    {
      target: "knowledge-explain",
      title: "Explain an error",
      body: "Paste a TM1 error message and press Explain. The Troubleshooter agent checks the real objects the error mentions against the live model, then explains what happened and how to fix it, with a severity when it recognizes the error type.",
    },
  ],

  "/memory": [
    {
      target: "memory-add",
      title: "Add memory",
      body: "Record something TM1 cannot tell the assistant: a run sequence, convention, caution, known issue or note, optionally tied to a cube, dimension, process, chore or rule by name. With knowledge write access it is in use at once; otherwise it waits for approval.",
    },
    {
      target: "memory-proposals",
      title: "Waiting for approval",
      body: "Proposals from teammates and suggestions from the assistant itself. None of these reach the assistant until a person approves them.",
    },
    {
      target: "memory-review",
      title: "Approve or reject",
      body: "Approve puts an entry in use from the assistant's next message; Reject discards it. Both need knowledge write access.",
    },
    {
      target: "memory-approved",
      title: "In use",
      body: "Approved entries go to the assistant in every conversation, and it cites them as organization knowledge.",
    },
    {
      target: "memory-search",
      title: "Search",
      body: "Filter the entries in use by an object name or by words in the text.",
    },
    {
      target: "memory-actions",
      title: "Edit, History, Archive",
      body: "Edit saves a new version and keeps the old one, History lists every version newest first, and Archive stops the assistant using the entry. These need knowledge write access.",
    },
  ],
  "/chat": [
    {
      target: "chat-new",
      title: "Start a new conversation",
      body: "Clears the screen and starts a fresh thread. Your earlier conversations stay in the list below.",
    },
    {
      target: "chat-history",
      title: "Search your conversations",
      body: "Type part of a title to filter your saved conversations. They are grouped by when they started.",
    },
    {
      target: "chat-conversations",
      title: "Reopen, share, rename or delete",
      body: "Click a conversation to reopen it. Hover over one to share it with your organization as read-only (the people icon), rename it, or delete it. Deleting permanently removes it and its message history.",
    },
    {
      target: "chat-layout",
      title: "Arrange the screen",
      body: "Maximize the chat to fill the window (Esc restores it). Next to it are buttons that show or hide the conversation list and the agent panel.",
    },
    {
      target: "chat-server",
      title: "Choose the TM1 server",
      body: "When you have more than one server, pick which one the agent reads and answers about. Each one is labelled with its environment, such as DEV or PROD.",
    },
    {
      target: "chat-model",
      title: "Pick the model",
      body: "Auto chooses the model for each message: Fast for plain questions, Balanced for TI work and troubleshooting, Best for architecture, review or a PROD server. You can also fix Fast, Balanced or Best yourself. Each answer says which model it used.",
    },
    {
      target: "chat-agent",
      title: "Choose a specialist agent",
      body: "A specialist agent gets live TM1 tools for its job. 'No agent' answers from general TM1 knowledge only, with no access to your model.",
    },
    {
      target: "chat-tasks",
      title: "Start from a common task",
      body: "Generate or explain TI, write MDX, review rules or feeders, or document a cube. Each button picks the right agent and starts the request; you finish it with the cube or process name.",
    },
    {
      target: "chat-messages",
      title: "Read and reuse answers",
      body: "Answers show which tools were called and the evidence behind them. Charts can be changed and exported to CSV, Excel or PNG. Hover a message to copy it or load your own question back into the box to edit and resend, and click Listen to hear an answer read aloud.",
    },
    {
      target: "chat-attach",
      title: "Attach files",
      body: "Attach up to 5 files of up to 15 MB each: PDF, JPG, PNG, DOCX, or a TI process as .pro or .txt. The model reads them directly, for example an error screenshot or a local copy of a process to compare with the server.",
    },
    {
      target: "chat-input",
      title: "Ask your question",
      body: "Type what you want to accomplish. Enter sends; Shift+Enter starts a new line.",
    },
    {
      target: "voice-input",
      title: "Dictate instead",
      body: "Speak your question and it is transcribed into the box. Nothing is sent until you press Send, and the answer is read back aloud.",
    },
    {
      target: "chat-hands-free",
      title: "Hands-free conversation",
      body: "Just talk: it sends when you stop, answers aloud, then listens again. Say 'stop' or click to end. The speaker button next to it mutes spoken answers.",
    },
    {
      target: "chat-agent-panel",
      title: "What the agent may do",
      body: "Shows the selected agent's description, how many tool rounds it may use, its allowed tools and its safety rules. Click a tool to start a prompt that uses it.",
    },
    {
      target: "chat-timeline",
      title: "Tool calls and drafted changes",
      body: "Every tool call in this conversation, with its result and how long it took. When an agent drafts a change, a card here lets you execute it, run it, discard it or roll it back. Nothing touches the live server until someone with the right permission confirms, and every action is audited.",
    },
    {
      target: "chat-referenced",
      title: "Referenced objects",
      body: "The TM1 objects the AI has looked up in this conversation, so you can see what its answer was based on.",
    },
  ],
  "/team": [
    {
      target: "team-report-incident",
      title: "Report an incident",
      body: "Describe what is wrong, pick the server and the cube or process, and set the severity and how far back to look. PA-Copilot then checks recent changes, runs, failures and model differences and ranks the likely causes. It only reads.",
    },
    {
      target: "team-new-work-item",
      title: "New work item",
      body: "Create a work item using your team's own reference (for example PBI #1234) and a title. You are taken straight to its page.",
    },
    {
      target: "team-work-items",
      title: "Work items",
      body: "Every work item with its status and when it was last updated. Click one to see its full story, from investigation through to deployment.",
    },
    {
      target: "team-filters",
      title: "Filter and search",
      body: "Narrow the list by status (Open, In progress, Resolved, Closed) or search by reference or title.",
    },
    {
      target: "team-awaiting",
      title: "Waiting for approval",
      body: "Drafted changes that passed validation and are waiting to be applied, on servers you can use. Click one to open it for review.",
    },
    {
      target: "team-shared",
      title: "Shared conversations",
      body: "Conversations colleagues have shared, read-only. Share your own from the AI Assistant's history with the people icon.",
    },
    {
      target: "team-recent",
      title: "Recent changes",
      body: "Changes from the last 14 days on servers you can use, with their status. Click one to open it.",
    },
    {
      target: "team-health",
      title: "Model health",
      body: "The latest health score and grade for each server you can use. Run a new scan from the Model Health page.",
    },
  ],
  "/team/[id]": [
    {
      target: "work-item-header",
      title: "The work item",
      body: "Its reference, title, who opened it and when. For an incident, it also shows the severity and the affected cube or process.",
    },
    {
      target: "work-item-status",
      title: "Change the status",
      body: "Move the item between Open, In progress, Resolved and Closed. The change is saved straight away and recorded on the timeline.",
    },
    {
      target: "work-item-progress",
      title: "Progress",
      body: "The checklist of steps this work item has completed so far, worked out from its linked records.",
    },
    {
      target: "work-item-investigation",
      title: "Incident investigation",
      body: "For incidents: the suspected causes ranked with their evidence, and what to do about each. Every mitigation opens a change or a diagnosis rather than acting by itself, and 'Investigate again' takes a fresh, read-only look.",
    },
    {
      target: "work-item-findings",
      title: "What the team found",
      body: "Write the root cause and the resolution in plain words. A Save button appears once you edit, and the timeline records who saved it and when.",
    },
    {
      target: "work-item-links",
      title: "Linked records",
      body: "The shared conversations and TM1 changes tied to this item, with their status. Click one to open it, or use the unlink icon to remove the link.",
    },
    {
      target: "work-item-link",
      title: "Link a record",
      body: "Link a shared conversation, or a TM1 change from the last 90 days on servers you can use, with an optional note. Only shared conversations can be linked.",
    },
    {
      target: "work-item-timeline",
      title: "Timeline",
      body: "The whole story in date order, oldest first, built from the records as they are now: who did what and when, with failures highlighted.",
    },
  ],
  "/team/conversations/[id]": [
    {
      target: "shared-conversation-back",
      title: "Back to Team",
      body: "Returns to the Team page and its list of shared conversations.",
    },
    {
      target: "shared-conversation-header",
      title: "A shared conversation",
      body: "Who shared it and when it started. It is read-only: only its owner can continue it, and anyone else starts their own in the AI Assistant.",
    },
    {
      target: "shared-conversation-messages",
      title: "The conversation",
      body: "The questions and PA-Copilot's answers in order, with who asked and when.",
    },
  ],
  "/connections": [
    {
      target: "connections-new",
      title: "Add a TM1 server",
      body: "Opens the New TM1 Connection form. Choose Native (on-prem), Planning Analytics as a Service (IBM Cloud API key) or Planning Analytics on Cloud (non-interactive account). Then set who can use it and whether it is DEV, QA or PROD. Credentials are encrypted at rest, and the password is never shown again after saving.",
    },
    {
      target: "connections-list",
      title: "Your connections",
      body: "Every TM1 server you can use: your own, plus the ones shared with your organization. Click a name to open its details.",
    },
    {
      target: "connections-badges",
      title: "Sharing, environment and status",
      body: "Private or Shared shows who can use the connection. 'Member's private' means an admin can manage it but not use it. DEV, QA and PROD set the rules for changes: DEV needs the deploy right, QA needs the 'deploy to QA' right, and PROD needs the 'deploy to PROD' right plus a second person to approve. The assistant is read-only on PROD.",
    },
    {
      target: "connections-actions",
      title: "Details, test, edit, delete",
      body: "View details lists the server's cubes, dimensions, processes and chores. Test checks that PA-Copilot can log in and says what is wrong if it can't. Edit keeps the current password unless you type a new one. Delete removes only the stored connection and its credentials; the TM1 server itself is not touched.",
    },
    {
      target: "connections-gateways",
      title: "Gateways for private networks",
      body: "For a TM1 server inside a company network, such as a 192.168.x.x address. Install a gateway once per network on an always-on Windows machine that can reach TM1. It connects out, so no firewall port is opened.",
    },
    {
      target: "connections-gateway-add",
      title: "Add a gateway",
      body: "Name it after the network it serves. You then get a download link and setup commands with its key, shown only once. After that, create a Native connection and choose this gateway under 'Reached through'.",
    },
    {
      target: "connections-gateway-actions",
      title: "Manage a gateway",
      body: "Each gateway shows whether it is online, when it was last seen and how many connections use it. New key replaces the key, so the old one stops working: use it if the key was lost. The bin icon removes the gateway.",
    },
  ],
  "/connections/[id]": [
    {
      target: "connection-detail-header",
      title: "This connection",
      body: "The connection's name, whether it is active, and its address, port, SSL and user.",
    },
    {
      target: "connection-detail-extract",
      title: "Extract metadata",
      body: "Reads the model and builds the dependency graph that relationship, impact and unused-object answers rely on. It only reads from TM1. Run it once, then again after the model changes.",
    },
    {
      target: "connection-detail-tabs",
      title: "Browse the model",
      body: "Switch between Cubes, Dimensions, Processes and Chores, read live from the TM1 server. Control objects are left out, and each tab shows its count.",
    },
    {
      target: "connection-detail-changes",
      title: "Recent changes",
      body: "The latest five draft and deployed changes on this connection, each with its status.",
    },
    {
      target: "connection-detail-view-all",
      title: "Go to Deployments",
      body: "Opens Deployments filtered to this connection, where you review, execute or roll back changes.",
    },
  ],
  "/metadata": [
    {
      target: "metadata-connection",
      title: "Pick a connection",
      body: "Choose which TM1 server to explore. Switching connections clears the selected object.",
    },
    {
      target: "metadata-search",
      title: "Search objects",
      body: "Type part of a name to filter the cube, dimension, process and chore lists below.",
    },
    {
      target: "metadata-objects",
      title: "Objects and recently viewed",
      body: "Click any cube, dimension, process or chore to open it. The last six objects you opened on this connection are listed at the top under Recently Viewed.",
    },
    {
      target: "metadata-model-map",
      title: "Model map",
      body: "When the dependency map was last read from TM1, with how many objects and dependencies it holds and what was added or removed since the previous read. It is refreshed daily, and a warning appears once it is over 7 days old.",
    },
    {
      target: "metadata-extract",
      title: "Extract now",
      body: "Rebuilds the dependency map from the live model now. It only reads from TM1 and never writes.",
    },
    {
      target: "metadata-tab-overview",
      title: "Overview",
      body: "The object's details read live from TM1: a cube's dimensions and rules, a dimension's hierarchies, a process's datasource, parameters and Prolog, Metadata, Data and Epilog code, or a chore's process chain. Click a dimension or process to jump to it.",
    },
    {
      target: "metadata-tab-relationships",
      title: "Relationships",
      body: "What this object depends on, and what depends on it, from the dependency map. If the map hasn't been built yet, an Extract metadata button appears here.",
    },
    {
      target: "metadata-tab-graph",
      title: "Dependency graph",
      body: "An interactive map centred on this object. Search within it, toggle object types, use Fit view or Reset, and double-click a node or use Expand neighbors to grow it. A node's panel can open that object, discuss it with the AI or show its deployments.",
    },
    {
      target: "metadata-tab-impact",
      title: "Impact",
      body: "What changing or deleting this object would affect, ranked by severity, from the dependency map. Switch between 'If changed' and 'If deleted'. It also lists what the map cannot see.",
    },
    {
      target: "metadata-tab-changes",
      title: "Recent changes",
      body: "Drafts and deployments that target this object. Click one to open it in Deployments.",
    },
    {
      target: "metadata-tab-ai",
      title: "AI analysis",
      body: "Opens the AI Workspace with this object already in context. You can ask it to explain the object, analyse its impact, discuss it with the Architect or Developer, or generate documentation.",
    },
  ],
  "/deployments": [
    {
      target: "governance-connection",
      title: "Pick a connection",
      body: "Changes are listed per TM1 connection. Switch here to see another server's change log.",
    },
    {
      target: "governance-new-change",
      title: "Draft a change by hand",
      body: "Create a draft to update a cube's rules, or to create, update or delete a process. It is only a draft: nothing is applied to TM1 until someone reviews and executes it.",
    },
    {
      target: "governance-changes",
      title: "Change log",
      body: "Every change on this connection, drafted by you or by the AI agents, with its type, time and status. Click one to review it. Every execute and rollback is audited.",
    },
    {
      target: "governance-review",
      title: "Review panel",
      body: "Everything about the selected change: status, any errors, lifecycle, checks, the proposed content, impact and the actions you can take.",
    },
    {
      target: "governance-validation",
      title: "Validation errors",
      body: "TM1 reported errors in the proposed code, by section and line. A change with validation errors cannot be executed.",
    },
    {
      target: "governance-lifecycle",
      title: "Lifecycle and checks",
      body: "Lifecycle shows where the change is (requested, analysed, validated, approved, applied, verified), as read from the record. Checks before approval lists what the change was checked against before it reaches you, each marked passed, failed or worth a look.",
    },
    {
      target: "governance-diff",
      title: "Current vs proposed",
      body: "For rules and process changes: the content on the server now next to what the change would write. Only sections that differ are shown.",
    },
    {
      target: "governance-cell-writes",
      title: "Cell writes",
      body: "For a cell-write change: each cell, the value it holds now and the new value. Values that change are in bold. The current values are read again and saved at the moment the change is applied.",
    },
    {
      target: "governance-run-plan",
      title: "Process run plan",
      body: "For a process run: the parameter values it will use, what it writes to and which processes it calls. A run cannot be rolled back.",
    },
    {
      target: "governance-impact",
      title: "Impact",
      body: "What this change affects, from the dependency map. If critical or high-severity objects are affected, you must tick that you have reviewed them before you can execute.",
    },
    {
      target: "governance-discuss",
      title: "Discuss in AI Chat",
      body: "Opens AI Chat to explain the change's impact and risk and to suggest whether it is safe to deploy.",
    },
    {
      target: "governance-promotion",
      title: "Promote and package",
      body: "Once a change has been applied here and not rolled back, Promote creates a draft of it on the next environment (DEV to QA, QA to PROD), where it is checked again and needs approval. Deployment package shows where the change has been, who approved it, its checks, impact, approval rule and rollback plan, and can be downloaded as JSON.",
    },
    {
      target: "governance-actions",
      title: "Execute, discard or roll back",
      body: "Execute applies a draft to the live server: it saves the current state, writes, verifies, and restores the saved state if verification fails. It needs the deploy right for the connection's environment, and on PROD it must be approved by someone other than the requester. Discard rejects a draft without applying it. Roll back restores the saved state, but refuses if someone has changed the object since.",
    },
  ],
  "/health": [
    {
      target: "health-connection",
      title: "Pick a connection",
      body: "Choose which TM1 model to score.",
    },
    {
      target: "health-scan",
      title: "Scan now",
      body: "Runs a fresh health scan of the model and its process runs. It can take a few minutes. Once a model has been scanned, it is rescanned daily.",
    },
    {
      target: "health-score",
      title: "Health score",
      body: "A score out of 100 with a grade: A is 90 or more, B 75+, C 60+, D 40+, and F below 40. It shows when the model was scanned, the recent scores and any notes about what could not be analysed.",
    },
    {
      target: "health-deductions",
      title: "Where the points went",
      body: "Points are deducted per finding, capped per category: critical rule findings, process errors, rule warnings, performance regressions, processes that failed in the last 7 days, other process findings and unused objects. Each line lists the objects that cost points.",
    },
    {
      target: "health-performance",
      title: "Performance",
      body: "Built from runs collected from TM1's message log and from PA-Copilot's own runs. It lists regressions (a latest run over twice the median of earlier runs), the slowest processes by median time, and failures in the last 7 days. What it can't measure is listed at the bottom.",
    },
  ],
  "/alerts": [
    {
      target: "alerts-new-rule",
      title: "Create a rule",
      body: "Pick a server and what to watch for: a process failing, a process running much slower than its average, a dimension growing past a percentage, users or group membership changing, model objects changing, or a deployment being applied, failing or rolled back. Rules only read TM1, and the first check sets the baseline.",
    },
    {
      target: "alerts-email-notice",
      title: "Email isn't set up",
      body: "This deployment has no mail settings, so alerts appear on this page and on the bell only. An administrator can add SMTP settings to send them by email too.",
    },
    {
      target: "alerts-suggested",
      title: "Rules the assistant suggested",
      body: "When you ask the assistant to watch something, its rule waits here and is not checked. Turn on starts checking it every 15 minutes; Discard deletes it.",
    },
    {
      target: "alerts-status-tabs",
      title: "Open, acknowledged, resolved",
      body: "Switch between alerts nobody has handled yet, alerts someone has seen, and alerts that are closed.",
    },
    {
      target: "alerts-list",
      title: "What the rules found",
      body: "Each alert shows its severity, the server it came from, when it fired and whether it was emailed, followed by the details of what changed.",
    },
    {
      target: "alerts-alert-actions",
      title: "Acknowledge or resolve",
      body: "Acknowledge marks an alert as seen and moves it to the Acknowledged tab. Resolve closes it.",
    },
    {
      target: "alerts-rules",
      title: "Your rules",
      body: "Every active or paused rule, the server it watches, and when it was last checked. A rule that can't reach its server shows the error and how many checks in a row have failed.",
    },
    {
      target: "alerts-rule-actions",
      title: "Check now, pause, delete",
      body: "The refresh button runs an active rule straight away instead of waiting up to 15 minutes. Pause stops checks until you resume, and the bin deletes the rule.",
    },
  ],

  "/monitoring": [
    {
      target: "monitoring-ai-cost",
      title: "AI cost",
      body: "What the assistant cost over the last 30 days, worked out from the usage ledger.",
    },
    {
      target: "monitoring-ai-cost-figures",
      title: "Headline figures",
      body: "Total spend, cost per request, average and 95th-percentile response time, and the fallback rate (how often the first-choice model failed and a backup model answered). Also shown: what caching saved, an estimate of what AUTO model routing saved, and request and tool-call counts.",
    },
    {
      target: "monitoring-ai-cost-breakdown",
      title: "Where the spend goes",
      body: "Cost, request count and cost per request, split by agent, by model tier and by person. The top eight in each are shown.",
    },
    {
      target: "monitoring-usage",
      title: "AI usage by model",
      body: "Requests and tokens for each AI model over 30 days. The description line shows totals and the share of prompt tokens served from cache.",
    },
    {
      target: "monitoring-tools",
      title: "Tool executions",
      body: "Each lookup the assistant made against TM1 metadata, grouped by tool, with calls, successes, not-found answers, errors and average duration. Not found means the object doesn't exist; it is an answer, not a failure.",
    },
    {
      target: "monitoring-breakers",
      title: "TM1 circuit breakers",
      body: "Live state for each TM1 connection. Closed is healthy. Open means repeated failures have paused calls to that server for a cooldown. Half open means a trial call is being let through.",
    },
  ],

  "/reports": [
    {
      target: "reports-new",
      title: "New report",
      body: "Name the report, choose a PAfE workbook (or upload an .xlsx, .xlsm or .xlsb with the upload button) and pick XLSX or PDF output.",
    },
    {
      target: "reports-definitions",
      title: "Workbook reports",
      body: "Each report pairs a PAfE workbook with an output format. A registered Windows worker with Excel and PAfE refreshes it; this service never runs Excel itself.",
    },
    {
      target: "reports-status",
      title: "Report status",
      body: "Where each report stands: draft, active, paused or archived.",
    },
    {
      target: "reports-run-now",
      title: "Run now",
      body: "Queues one run for a worker to pick up. Clicking again in the same minute doesn't queue a duplicate.",
    },
    {
      target: "reports-history-link",
      title: "Runs and their history",
      body: "Runs start only when someone clicks Run now. The link opens the execution history, where you can follow each run and download its output.",
    },
  ],

  "/reports/workers": [
    {
      target: "workers-register",
      title: "Register a worker",
      body: "Give the Windows machine a name and you get a single-use enrollment token to run on it. The token is shown once and can't be retrieved again, so copy it before closing.",
    },
    {
      target: "workers-list",
      title: "Registered workers",
      body: "Every machine that can run reports, with its host name, OS, Excel version and PAfE version. The list refreshes every 15 seconds.",
    },
    {
      target: "workers-status",
      title: "Status and heartbeat",
      body: "Pending enrollment, online, busy, offline, disabled or error, based on how recently the worker last checked in. The Last heartbeat column shows when that was.",
    },
    {
      target: "workers-capabilities",
      title: "Verified capabilities",
      body: 'What the worker has proved it can do. A worker is only given work it has verified, so "none verified" means it won\'t get report runs.',
    },
    {
      target: "workers-toggle",
      title: "Disable or enable",
      body: "Disable takes a worker out of service without deleting it, and Enable brings it back.",
    },
  ],

  "/reports/executions": [
    {
      target: "executions-list",
      title: "Every run",
      body: "Each report run, including retries and failures, newest first. The list refreshes every five seconds while the page is open.",
    },
    {
      target: "executions-status",
      title: "Run status",
      body: "Queued, assigned, running, succeeded, failed, timed out, cancelled or retrying. The Trigger column says whether the run was started by hand or is a retry.",
    },
    {
      target: "executions-attempt",
      title: "Attempts",
      body: "Which attempt this is out of the maximum allowed. A retry is a new run linked to the one it replaces, so the history of what happened stays intact.",
    },
    {
      target: "executions-error",
      title: "Error",
      body: "The failure message for runs that didn't succeed. Open the run for the error code and whether it can be retried.",
    },
    {
      target: "executions-row",
      title: "Open a run",
      body: "Click any row to see its start and finish times, duration, correlation id and the PAfE automation trace log, and to download the files it produced.",
    },
  ],

  "/users": [
    {
      target: "users-signups",
      title: "Sign-up requests",
      body: "Super Admin only: everyone who signed up, from every workspace. Each person gets their own private workspace and can sign in once you approve them here.",
    },
    {
      target: "users-pending",
      title: "Pending requests",
      body: "People who asked to join your organization using its code.",
    },
    {
      target: "users-assign-role",
      title: "Assign a role",
      body: 'Choose the role the person gets when approved, or leave "No role yet" and assign one later.',
    },
    {
      target: "users-approve",
      title: "Approve or reject",
      body: "Approve lets the person sign in with the role you chose. Reject turns the request down.",
    },
    {
      target: "users-members",
      title: "All members",
      body: "Everyone in your organization, with their roles, registration status and whether the account is active.",
    },
    {
      target: "users-member-action",
      title: "Deactivate or reactivate",
      body: "Deactivate signs the person out at once and blocks sign-in until they are reactivated. Their account and data are kept. You can't deactivate yourself.",
    },
  ],

  "/settings": [
    {
      target: "settings-profile",
      title: "Your profile",
      body: "The username, email, name and account status of whoever is signed in.",
    },
    {
      target: "settings-profile-form",
      title: "Change your name",
      body: "Edit your first and last name and click Save. Both are required, and Save stays disabled until something changes.",
    },
    {
      target: "settings-theme",
      title: "Appearance",
      body: "Light, Dark, or System to follow your computer's setting. This only changes how the console looks to you.",
    },
    {
      target: "settings-organization",
      title: "Organization",
      body: "Your organization's code (the code people use to ask to join) and its plan. If your role can't view organization settings, this card says so.",
    },
    {
      target: "settings-org-form",
      title: "Rename the organization",
      body: "Change the organization name or its optional domain. Saving needs the organization.write permission.",
    },
  ],
};

/** The feature tour for a path. A key segment in brackets, as in
 * "/team/[id]", matches any one segment, so detail pages share a tour. */
export function featureTourFor(pathname: string): TourStep[] | undefined {
  if (FEATURE_TOURS[pathname]) return FEATURE_TOURS[pathname];

  const parts = pathname.split("/");
  const key = Object.keys(FEATURE_TOURS).find((candidate) => {
    const pattern = candidate.split("/");
    return (
      pattern.length === parts.length &&
      pattern.every(
        (segment, i) => segment === parts[i] || /^\[.+\]$/.test(segment),
      )
    );
  });

  return key ? FEATURE_TOURS[key] : undefined;
}
