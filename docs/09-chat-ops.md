# Chat Ops: git e pacotes pelo chat

Atalhos: @ops, @commit, @pack, @primer. Também funciona em frase natural ("commita meus arquivos", "gere um md do problema X pro Claude", "me dá o primer").

## Commit dos seus arquivos

A IA lista o que está não commitado, pergunta quais, lê o diff real, escreve a mensagem (tipo: resumo) e commita só o que você escolheu, em commits separados quando os assuntos forem diferentes. Recusa main/master, .enve arquivos de segredo, e nomes ambíguos. Desfazer:git reset --soft HEAD~1.

## Pacote .md para outra IA

A IA pergunta o problema, sugere até 6 arquivos (nome, trechos, alterações recentes e RAG), você escolhe ou cita os seus, e ela devolve o link /api/handoff/packs/<arquivo>.md(segredos mascarados). Arquivos em~/.assistente_local/packs(ouTASK_PACK_DIR), apagados após 30 dias.

## Continuação

Se a última resposta do Ops terminou com pergunta, a sua próxima mensagem continua a conversa dele. Uma tag como @heavy` desvia para outro fluxo.


## Zip de arquivos

Peça no chat, por exemplo: `me entregue os arquivos script.js, style.css e a pasta rag` (ou use a tag `@zip script.js rag`). O Ops monta UM `.zip` e devolve o link de download no chat.

- **Nomes aceitos:** nome simples (`script.js`), sufixo de caminho (`static/script.js`), caminho completo ou nome de pasta (`rag`). Arquivos e pastas de lugares diferentes podem ir no mesmo zip. Se o nome for ambíguo ou não existir, o Ops pede o caminho completo (mesma regra do commit, `resolve_names`).
- **Pastas inteiras:** entram todos os arquivos rastreados ou novos, respeitando o `.gitignore`. `.git`, `venv`, `node_modules` e `__pycache__` ficam de fora.
- **Segredos:** `.env`, chaves e certificados (`is_secret_path`) nunca entram; o Ops avisa o que ficou de fora.
- **Limites:** 500 arquivos e 50 MB (`ZIP_MAX_FILES` e `ZIP_MAX_BYTES` em `ops_core.py`).
- **Onde ficam:** na mesma pasta dos pacotes `.md` (`pack_dir()`), como `arquivos_AAAAMMDD_HHMMSS_nome.zip`, com retenção de 30 dias. Download em `GET /api/handoff/zips/{nome}`.
- **Proteção:** o link vem sempre da ferramenta `build_zip_files`; se o modelo citar um zip que a ferramenta não gerou, o sistema recusa e tenta de novo.
