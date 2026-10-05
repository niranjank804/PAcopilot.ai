# Answer accuracy — live run

Run 2026-10-05T18:38:31+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**10 / 11 correct (91%)** · median 8.5 s, slowest 8679.6 s · total $1.0738 · models: claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 4.0 | 0.015 | list_cubes:success |
| dimension_order | developer | yes | 7.1 | 0.016 | get_cube:success |
| cubes_with_rules | developer | yes | 10.6 | 0.0356 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 5.9 | 0.0236 | search_model_objects:success, get_dimension:success |
| cell_value | analyst | yes | 9.5 | 0.034 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rule_derived | developer | yes | 11.3 | 0.0307 | get_cube:success, inspect_cell:success |
| process_writes | developer | yes | 7.2 | 0.0307 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 5.4 | 0.0293 | get_process:success |
| missing_cube | developer | yes (re-scored) | 14.3 | 0.043 | get_cube:not_found, search_model_objects:success, search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 8.5 | 0.0266 | search_model_objects:success, list_processes:success |
| ti:paw_fixed_width_load | ti | **no** | 8679.6 | 0.7893 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success, lookup_tm1_function:success, lookup_tm1_function:success, lookup_tm1_function:success |

Re-scored: missing_cube — the answer said "There's no 'Sales_Forecast_2031'"; the check's pattern missed that wording. Pattern fixed and re-applied to the saved answer, with no new model call.
