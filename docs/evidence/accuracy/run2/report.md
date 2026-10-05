# Answer accuracy — live run

Run 2026-10-05T15:45:46+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**10 / 11 correct (91%)** · median 8.3 s, slowest 73.0 s · total $0.5278 · models: claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 5.1 | 0.0153 | list_cubes:success |
| dimension_order | developer | yes | 4.1 | 0.0157 | get_cube:success |
| cubes_with_rules | developer | yes | 19.9 | 0.0362 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 73.0 | 0.1888 | get_object_relationships:not_found, search_model_objects:success, get_dimension:success, get_dimension_attributes:success, search_model_objects:error, list_dimension_subsets:success |
| cell_value | analyst | yes | 10.2 | 0.0336 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rule_derived | developer | yes | 8.1 | 0.0223 | inspect_cell:success |
| process_writes | developer | yes | 8.3 | 0.0305 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 7.9 | 0.0372 | search_model_objects:success, get_process:success |
| missing_cube | developer | yes (re-scored) | 6.0 | 0.0171 | search_model_objects:success |
| missing_process | developer | yes | 10.3 | 0.0264 | search_model_objects:success, list_processes:success |
| ti:paw_fixed_width_load | ti | **no** | 42.1 | 0.1047 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success, search_model_objects:success, get_process:success, get_process:success |

Re-scored: missing_cube — a correct answer ('no cube by that name exists') the first check's phrase list missed; the check was widened and re-applied to the saved answer, with no new model call.
