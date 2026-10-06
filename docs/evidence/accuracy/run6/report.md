# Answer accuracy — live run

Run 2026-10-05T19:20:22+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**17 / 18 correct (94%)** · median 9.2 s, slowest 192.0 s · total $1.139 · models: claude-haiku-4-5, claude-opus-5, claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 5.5 | 0.0786 | list_cubes:success |
| dimension_order | developer | yes | 3.7 | 0.0158 | get_cube:success |
| cubes_with_rules | developer | yes | 10.9 | 0.0364 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 6.9 | 0.0235 | search_model_objects:success, get_dimension:success |
| cell_value | analyst | yes | 11.4 | 0.0792 | get_cell_values:success, get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success |
| rule_derived | developer | yes | 10.3 | 0.0304 | get_cube:success, inspect_cell:success |
| process_writes | developer | yes | 9.2 | 0.031 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 4.7 | 0.0284 | get_process:success |
| chores | administrator | yes (re-scored) | 4.7 | 0.0564 | list_chores:success |
| process_parameters | documentation | yes | 7.3 | 0.0164 | get_process:success |
| datasource_file | troubleshooter | yes | 6.6 | 0.0847 | get_process:success |
| string_cell | analyst | yes | 14.6 | 0.0359 | search_model_objects:success, get_cube:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rules_reading_cube | architect | yes | 18.8 | 0.1022 | search_model_objects:success, get_cube_data_flow:success |
| cubes_using_dimension | architect | yes | 22.9 | 0.091 | search_model_objects:success, search_model_objects:success, get_object_relationships:not_found, get_cube:success, list_cubes:success, get_cube:success |
| leaf_count | developer | yes | 6.6 | 0.0241 | search_model_objects:success, get_dimension:success |
| missing_cube | developer | yes | 13.4 | 0.0449 | get_cube:not_found, search_model_objects:success, search_model_objects:success, search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 7.5 | 0.0253 | get_process:not_found, search_model_objects:success |
| ti:paw_fixed_width_load | ti | **no** | 192.0 | 0.3348 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success, lookup_tm1_function:success, lookup_tm1_function:success, lookup_tm1_function:success |

Re-scored: chores — the answer ('no chores are set up') was correct; the check's pattern contained stray control characters from an editing mistake and could not match. Fixed and re-applied to the saved answer, with no new model call.
