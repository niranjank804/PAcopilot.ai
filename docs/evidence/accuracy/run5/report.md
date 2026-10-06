# Answer accuracy — live run

Run 2026-10-05T19:13:58+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**17 / 18 correct (94%)** · median 8.3 s, slowest 281.0 s · total $1.2637 · models: claude-haiku-4-5, claude-opus-5, claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 4.4 | 0.0157 | list_cubes:success |
| dimension_order | developer | yes | 3.7 | 0.016 | get_cube:success |
| cubes_with_rules | developer | yes | 10.3 | 0.0359 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 5.7 | 0.0238 | get_dimension:success, search_model_objects:success |
| cell_value | analyst | yes | 12.2 | 0.0344 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rule_derived | developer | yes | 15.9 | 0.0547 | search_model_objects:success, get_cube:success, search_model_objects:success, search_model_objects:success, search_model_objects:success, inspect_cell:success |
| process_writes | developer | yes | 6.0 | 0.0305 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 4.7 | 0.0291 | get_process:success |
| chores | administrator | yes (re-scored) | 4.3 | 0.0121 | list_chores:success |
| process_parameters | documentation | yes | 3.6 | 0.0162 | get_process:success |
| datasource_file | troubleshooter | yes | 6.4 | 0.0938 | search_model_objects:success, get_process:success |
| string_cell | analyst | yes | 10.9 | 0.0367 | search_model_objects:success, get_cube:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rules_reading_cube | architect | yes | 32.7 | 0.1173 | search_model_objects:success, get_cube_data_flow:success, get_cube_rules:success |
| cubes_using_dimension | architect | yes | 20.5 | 0.0904 | search_model_objects:success, search_model_objects:success, get_object_relationships:not_found, list_cubes:success, get_cube:success, get_cube:success |
| leaf_count | developer | yes | 7.4 | 0.0247 | search_model_objects:success, get_dimension:success |
| missing_cube | developer | yes | 9.2 | 0.0259 | search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 8.3 | 0.0272 | search_model_objects:success, list_processes:success |
| ti:paw_fixed_width_load | ti | **no** | 281.0 | 0.5793 | search_knowledge_base:success, search_knowledge_base:success, get_coding_standards:success, search_model_objects:success, get_process:success, get_process:success |

Re-scored: chores — the answer ('no chores are set up') was correct; the check's pattern contained stray control characters from an editing mistake and could not match. Fixed and re-applied to the saved answer, with no new model call.
