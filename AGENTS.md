# Instruções do projeto

## Privacidade — arquivos que NUNCA devem ir para o git

- `conversa.log` é um log de sessão **privado**. Nunca commitar, versionar ou enviar para o GitHub.
- Qualquer arquivo de log/sessão (`.log`, conversas, backups) deve ser adicionado ao `.gitignore` antes de qualquer commit.
- Se um arquivo privado já estiver no git/história: remover com `git filter-repo` e fazer push forçado.

## Boas práticas

- Sempre verificar `git status` antes de commitar para garantir que nenhum arquivo privado foi incluído.
