# GestorLab - servidor do painel (FastAPI) para deploy no Dokploy.
# O agente do aluno continua rodando localmente nos PCs; aqui vai so o servidor.
FROM python:3.12-slim

WORKDIR /app

# Dependencias do servidor (mesmo arquivo usado para montar o pacote do professor).
COPY requirements-professor.txt .
RUN pip install --no-cache-dir -r requirements-professor.txt

# Codigo do servidor (main.py, auth.py, config.py, database.py, static/).
COPY server/ /app/

# Codigo do agente do aluno, servido para auto-atualizacao (o servidor le a versao dele
# e envia aos alunos desatualizados). Fonte unica: client/agent.py.
COPY client/agent.py /app/agent_update.py

# Dados gravaveis (banco, contas, config, logs) ficam num volume persistente.
# Monte um volume do Dokploy em /data para nao perder nada no redeploy.
ENV GESTORLAB_DATA=/data \
    GESTORLAB_BROWSER=0 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
CMD ["python", "main.py"]
