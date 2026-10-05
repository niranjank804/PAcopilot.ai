# Answer accuracy — live run

Run 2026-10-05T16:12:14+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**10 / 11 correct (91%)** · median 8.6 s, slowest 173.9 s · total $0.6085 · models: claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 5.3 | 0.0779 | list_cubes:success |
| dimension_order | developer | yes | 4.3 | 0.0159 | get_cube:success |
| cubes_with_rules | developer | yes | 10.7 | 0.0359 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 9.2 | 0.0237 | search_model_objects:success, get_dimension:success |
| cell_value | analyst | yes | 8.6 | 0.0813 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, search_model_objects:success, get_cell_values:success |
| rule_derived | developer | yes | 10.9 | 0.0402 | search_model_objects:success, get_cube:success, inspect_cell:success |
| process_writes | developer | yes | 7.5 | 0.0304 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 8.1 | 0.0382 | search_model_objects:success, get_process:success |
| missing_cube | developer | yes | 5.7 | 0.025 | search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 9.4 | 0.0388 | get_process:not_found, search_model_objects:success, search_model_objects:success, search_model_objects:success |
| ti:paw_fixed_width_load | ti | **no** | 173.9 | 0.2012 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success, search_model_objects:success, get_process:success, get_process:success |
