# Answer accuracy — live run

Run 2026-10-05T19:42:39+00:00 against TM1 11.0.00100.927 (Planning Sample), real model, real tools.
Truth read from TM1 with TM1py at run time; deterministic checks, no model grading.

**17 / 18 correct (94%)** · median 7.4 s, slowest 404.8 s · total $1.609 · models: claude-haiku-4-5, claude-opus-5, claude-sonnet-5

| Case | Agent | Correct | Seconds | Cost $ | Tools |
|---|---|---|---|---|---|
| list_cubes | developer | yes | 5.2 | 0.0785 | list_cubes:success |
| dimension_order | developer | yes | 4.1 | 0.0163 | get_cube:success |
| cubes_with_rules | developer | yes | 10.6 | 0.0361 | list_cubes:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success, get_cube:success |
| element_count | developer | yes | 5.5 | 0.0237 | search_model_objects:success, get_dimension:success |
| cell_value | analyst | yes | 11.8 | 0.0795 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rule_derived | developer | yes | 10.5 | 0.0319 | get_cube:success, inspect_cell:success |
| process_writes | developer | yes | 6.3 | 0.0306 | search_model_objects:success, analyze_process_references:success |
| process_datasource | developer | yes | 7.3 | 0.0373 | search_model_objects:success, get_process:success |
| chores | administrator | yes | 4.7 | 0.0562 | list_chores:success |
| process_parameters | documentation | yes | 3.8 | 0.0162 | get_process:success |
| datasource_file | troubleshooter | yes | 3.7 | 0.0849 | get_process:success |
| string_cell | analyst | yes | 11.0 | 0.0297 | get_cube:success, list_dimension_elements:success, list_dimension_elements:success, get_cell_values:success |
| rules_reading_cube | architect | yes | 7.4 | 0.0961 | get_cube_data_flow:success |
| cubes_using_dimension | architect | yes | 27.5 | 0.0895 | search_model_objects:success, search_model_objects:success, get_object_relationships:not_found, list_cubes:success, get_cube:success, get_cube:success |
| leaf_count | developer | yes | 6.0 | 0.0243 | search_model_objects:success, get_dimension:success |
| missing_cube | developer | yes | 12.3 | 0.0458 | get_cube:not_found, search_model_objects:success, search_model_objects:success, search_model_objects:success, list_cubes:success |
| missing_process | developer | yes | 7.6 | 0.0269 | list_processes:success, search_model_objects:success |
| ti:paw_fixed_width_load | ti | **no** | 404.8 | 0.8055 | get_coding_standards:success, search_knowledge_base:success, search_knowledge_base:success, search_knowledge_base:success, list_processes:success, get_process:success |
