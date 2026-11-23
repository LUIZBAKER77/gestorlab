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
- **Antes do 1º deploy**, defina em **Environment** a variável
  `GESTORLAB_ADMIN_PASSWORD` com uma senha forte — assim a conta `admin` inicial
  não usa a padrão pública (`padrao#jf`), que está visível no código-fonte.
- Acesse o domínio e entre com o usuário `admin` e essa senha. Crie as contas da
  equipe na aba **Equipe** e **exclua a `admin`**. Depois importe os alunos pela
  planilha.

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

## Criptografia (TLS) com certificado próprio — RECOMENDADO

Sem isso, tudo trafega em texto puro (senhas, token, telas) e **qualquer PC da rede
pode se passar pelo servidor e controlar as máquinas**. Com TLS ligado, o tráfego é
criptografado e o agente só obedece o servidor que apresentar o certificado certo
(um invasor é recusado). Funciona mesmo com IP interno, sem domínio.

A chave privada é gerada **dentro do servidor** e nunca sai dele. Você só copia uma
linha (a impressão digital) do log para o agente. Passo a passo:

1. No Dokploy, aba **Environment**, adicione:
   ```
   GESTORLAB_TLS=1
   ```
   Salve e dê **Deploy**.
2. Abra a aba **Logs**. Logo no início vai aparecer um bloco assim:
   ```
   [GESTORLAB] TLS LIGADO (certificado autoassinado)
   ... "server_cert_sha256":
   4939609616887ff8...  (64 caracteres hex)
   ```
   Copie essa linha de 64 caracteres (a impressão digital).
3. Me mande essa impressão digital: eu coloco no `config.json` dos agentes
   (campos `"secure": true` e `"server_cert_sha256": "..."`), gero o pacote e você
   redistribui. A partir daí o acesso ao servidor passa a ser `https://10.11.1.41:8127`.
4. No navegador, ao abrir o painel em `https://...`, vai aparecer um aviso de
   "certificado não confiável" (porque é autoassinado) — é esperado; clique em
   avançar/continuar. Para os **agentes** não tem aviso: eles verificam pela
   impressão digital fixada.

Enquanto o TLS não estiver ligado, mantenha o uso só na rede interna e ciente de
que o tráfego não é criptografado.

## Observações

- O pacote **1_PROFESSOR** (servidor `.exe` local) deixa de ser necessário: o TE
  agora só abre o domínio no navegador e faz login. Dá para manter o `.exe` como
  alternativa offline, mas o fluxo normal passa a ser a nuvem.
- Variáveis já embutidas na imagem: `GESTORLAB_DATA=/data` e `GESTORLAB_BROWSER=0`.
- Variável recomendada em **Environment**: `GESTORLAB_ADMIN_PASSWORD` (senha
  inicial do admin; só vale na primeira execução, depois fica no banco).
- A porta interna é sempre `8000`; quem publica para fora é o Dokploy/Traefik.
- A descoberta UDP tenta subir dentro do contêiner e, se não conseguir, apenas
  avisa no log e segue — não derruba o servidor.
