# Answer accuracy — live run

Run 2026-10-05T15:42:14+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**10 / 11 correct (91%)** · median 12.5 s, slowest 66.1 s · total $0.4973 · models: claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 5.0 | 0.0149 | list_cubes:success |
| dimension_order | developer | yes | 4.8 | 0.0161 | get_cube:success |
| cubes_with_rules | developer | yes | 10.9 | 0.0365 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 66.1 | 0.1793 | search_model_objects:success, get_dimension:success, get_dimension_attributes:success, search_model_objects:success, list_dimension_subsets:success, get_subset:success |
| cell_value | analyst | yes | 18.9 | 0.0347 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rule_derived | developer | yes | 16.7 | 0.0384 | search_model_objects:success, get_cube:success, inspect_cell:success |
| process_writes | developer | yes | 8.0 | 0.0309 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 9.0 | 0.037 | search_model_objects:success, get_process:success |
| missing_cube | developer | yes | 17.6 | 0.0426 | get_cube:not_found, search_model_objects:success, search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 12.5 | 0.0325 | get_process:not_found, search_model_objects:success, search_model_objects:success |
| ti:paw_fixed_width_load | ti | **no** | 21.1 | 0.0344 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success |
