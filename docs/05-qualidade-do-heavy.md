# Qualidade das respostas do heavy

Módulos em backend/graph/ que checam, por código, o que o heavy lê e o que ele devolve. Nenhum deles chama modelo.

## Antes do heavy responder (context gatherer)

- checklist.py: extract_checklist cria um item por arquivo citado no pedido e gatherer_coverage_part devolve as regras de cobertura mais o checklist. Entra no contexto do gatherer em context_gatherer_node.
- snippet_validator.py: validate_snippets remove do dossiê os blocos de código cujas linhas não existem, em ordem, no arquivo real. Roda logo depois de ground_dossier.

## Depois do heavy responder

- answer_guard.py: finalize_answer troca menções a dossiê/coletor/tool calls (scrub_meta_references), detecta saída em loop (detect_repetition) e marca nomes, rotas e arquivos que não existem nos fatos lidos (ground_answer). Não roda quando o usuário pede o retorno bruto de uma tool (wants_raw_output).
- heavy_analyzer_node refaz a resposta uma vez quando ela entra em loop (_retry_if_degenerate).

## Regras e fatos injetados no prompt

- heavy_rules.py: HEAVY_OUTPUT_RULES, regras de saída do heavy.
- supported_formats.py: READ_SUPPORT_FACTS descreve o que as tools de leitura realmente aceitam. É injetado quando o usuário pergunta sobre extensões ou formatos (asks_about_read_support).

## Leitura de arquivos de texto

read_text_for_tools em file_readers.py tenta UTF-8, depois cp1252 e latin-1, para ler arquivos como .bat salvos pelo Windows.

## Testes

backend/graph/tests/: test_answer_guard.py, test_snippet_validator.py, test_checklist.py, test_supported_formats.py, test_heavy_rules.py.
