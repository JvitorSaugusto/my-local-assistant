# Chat Ops: git e pacotes pelo chat

Atalhos: @ops, @commit, @pack, @primer. Também funciona em frase natural ("commita meus arquivos", "gere um md do problema X pro Claude", "me dá o primer").

## Commit dos seus arquivos

A IA lista o que está não commitado, pergunta quais, lê o diff real, escreve a mensagem (tipo: resumo) e commita só o que você escolheu, em commits separados quando os assuntos forem diferentes. Recusa main/master, .enve arquivos de segredo, e nomes ambíguos. Desfazer:git reset --soft HEAD~1.

## Pacote .md para outra IA

A IA pergunta o problema, sugere até 6 arquivos (nome, trechos, alterações recentes e RAG), você escolhe ou cita os seus, e ela devolve o link /api/handoff/packs/<arquivo>.md(segredos mascarados). Arquivos em~/.assistente_local/packs(ouTASK_PACK_DIR), apagados após 30 dias.

## Continuação

Se a última resposta do Ops terminou com pergunta, a sua próxima mensagem continua a conversa dele. Uma tag como @heavy` desvia para outro fluxo.
