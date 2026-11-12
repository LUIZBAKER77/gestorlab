# Deploy do GestorLab no Dokploy

O servidor do painel (FastAPI) agora roda num servidor na nuvem, via Dokploy,
em vez do PC do professor. O **agente do aluno continua rodando localmente** em
cada PC e passa a se conectar ao servidor pela internet (HTTPS/WSS).

> ⚠️ **Importante:** o agente captura tela e controla os PCs dos alunos. Esses
> dados vão trafegar pela internet, então o acesso **tem que ser por HTTPS/WSS**
> (o Dokploy já faz isso com Let's Encrypt) e você **deve** definir uma
> `agent_key` (abaixo), senão qualquer um poderia registrar um "aluno" no servidor.

## 1. Criar a aplicação no Dokploy

1. **New Project** → dentro dele **Create Service → Application**.
2. **Provider:** GitHub → selecione este repositório, branch `main`.
3. **Build Type:** `Dockerfile` (caminho `./Dockerfile` — já está pronto na raiz).
4. **Deploy** uma primeira vez para ele construir a imagem.

## 2. Volume de dados (NÃO pule)

O banco, as contas e a configuração ficam em `/data`. Sem um volume, tudo é
perdido a cada redeploy.

- Na aba **Advanced → Volumes / Mounts**, adicione um **Volume Mount**:
  - **Mount Path:** `/data`
  - **Volume Name:** `gestorlab-dados` (qualquer nome)

## 3. Domínio e porta

- Aba **Domains** → **Add Domain**:
  - **Host:** o domínio que você vai usar (ex.: `gestorlab.suaescola.com`)
  - **Container Port:** `8000`
  - **HTTPS:** ligado (Let's Encrypt). O Dokploy cuida do certificado.
- Faça o redeploy. Acesse `https://gestorlab.suaescola.com`.

## 4. Primeiro acesso / migrar seus dados

**Opção A — começar do zero (sistema novo, sem alunos):**
- Acesse o domínio e entre com a conta provisória `admin` e a senha padrão
  (`padrao#jf`). Crie as contas da equipe na aba **Equipe** e **exclua a `admin`**.
  Depois importe os alunos pela planilha.

**Opção B — levar o banco que você já tem (1790 alunos + suas contas):**
1. Pegue o `gestorlab.db` atual (do PC/pacote do professor, pasta `dados`).
2. No Dokploy, pare a aplicação.
3. Coloque o arquivo no volume, no caminho `/data/gestorlab.db`
   (pela aba de arquivos do Dokploy, ou via SSH no servidor, na pasta do volume).
   Leve junto o `server_config.json` se quiser manter a mesma `secret_key`.
4. Inicie a aplicação.

## 5. Segurança: defina a `agent_key`

No arquivo `/data/server_config.json` (dentro do volume), defina:

```json
{ "agent_key": "uma-chave-secreta-bem-grande" }
```

A **mesma** chave vai em cada agente (passo 6). Reinicie a aplicação depois.
Troque também a senha do seu usuário admin por uma forte no primeiro login.

## 6. Configurar os agentes dos alunos

Em cada PC do aluno, edite `2_ALUNO\dados\config.json` e aponte para o domínio.
Use a **URL completa** — ela já define HTTPS/WSS automaticamente:

```json
{
  "server_host": "https://gestorlab.suaescola.com",
  "agent_key": "uma-chave-secreta-bem-grande",
  "require_student_login": true
}
```

- Não use mais `"auto"` (a descoberta por UDP só funciona na rede local).
- Com a URL `https://...`, não precisa informar `server_port`.
- Para rede local sem HTTPS (teste), dá para usar `"server_host": "192.168.x.x"`
  com `"server_port": 8000` — o modo antigo continua funcionando.

## Observações

- O pacote **1_PROFESSOR** (servidor `.exe` local) deixa de ser necessário: o TE
  agora só abre o domínio no navegador e faz login. Dá para manter o `.exe` como
  alternativa offline, mas o fluxo normal passa a ser a nuvem.
- Variáveis já embutidas na imagem: `GESTORLAB_DATA=/data` e `GESTORLAB_BROWSER=0`.
- A porta interna é sempre `8000`; quem publica para fora é o Dokploy/Traefik.
- A descoberta UDP tenta subir dentro do contêiner e, se não conseguir, apenas
  avisa no log e segue — não derruba o servidor.
