# 🖥️ GestorLab - Gerenciamento do Laboratório de Informática

Monitoramento em tempo real, bloqueio de tela, avisos, envio de arquivos e controle remoto dos computadores do laboratório (Windows 10/11, 100% em rede local).

Cada pacote é **um .exe + a pasta `app`** (Python embutido) + a pasta `dados` (suas configurações). **Copie sempre a pasta inteira**, não só o .exe.

---

## 👨‍🏫 Computador do Professor — pasta `1_PROFESSOR`

1. **Só na primeira vez:** botão direito em `liberar_firewall.bat` → *Executar como administrador*.
2. Dê duplo clique em **`GestorLab Professor.exe`**. O painel abre no navegador.
3. Pronto: o programa **inicia sozinho com o Windows** a partir daí (sem janela e sem abrir o navegador; para abrir o painel, dê duplo clique no .exe de novo ou acesse `http://localhost:8000`).

Na primeira execução o programa **gera uma senha aleatória** para o painel, mostrada em `dados\SENHA_INICIAL.txt`. Entre com ela e troque-a pelo botão **Configurações** (o painel avisa enquanto a senha inicial estiver em uso; o arquivo é apagado ao trocar). Trocar a senha encerra as sessões abertas em outros navegadores.

## 👥 Computadores dos Alunos — pasta `2_ALUNO`

1. Copie a pasta `2_ALUNO` inteira para o PC do aluno (ex.: `C:\GestorLab`).
2. Dê duplo clique em **`GestorLab Aluno.exe`**. Ele passa a iniciar com o Windows e acha o professor sozinho na rede.

A configuração fica em `dados\config.json` (`"server_host": "auto"` procura o professor por broadcast UDP; ou coloque o IP, ex.: `"192.168.1.50"`).

## ⚙️ Início automático

| Comando | Efeito |
|---|---|
| (padrão) | O .exe se registra para iniciar com o Windows na primeira execução |
| `"GestorLab Professor.exe" --remover-inicio` | Desativa o início automático |
| `"GestorLab Professor.exe" --instalar-inicio` | Reativa |

O mesmo vale para `GestorLab Aluno.exe`. Se o programa fechar sozinho, o .exe o reinicia em segundos.

## 🔧 Configuração do servidor (`1_PROFESSOR\dados\server_config.json`)

| Campo | Para que serve |
|---|---|
| `admin_password` | Senha do painel |
| `secret_key` | Gerada automaticamente |
| `agent_key` | Opcional. Se preenchida, cada aluno precisa da mesma `agent_key` em `dados\config.json` |
| `port` / `discovery_port` | 8000 / 8001 |
| `open_browser` | Abre o navegador ao iniciar manualmente |
| `max_upload_mb` | Limite de envio de arquivos (40) |

Banco de alunos: `dados\gestorlab.db`. Logs: `dados\servidor.log`, `dados\agente.log`, `dados\lancador.log`.

**Atualizar versão:** gere os pacotes de novo (abaixo) e substitua tudo **menos a pasta `dados`**.

## 🛡️ Antivírus (SentinelOne)

Não há PyInstaller: o .exe é um lançador pequeno que roda o Python oficial embutido. Mesmo assim, o agente do aluno faz coisas que antivírus podem classificar como suspeitas (bloqueio de teclado, controle remoto, captura de tela, início automático). Sem liberação da TI não há garantia. Se bloquear, peça à TI para liberar a pasta do GestorLab (ou o certificado, se o executável for assinado no futuro).

## 🛠️ Para desenvolvedores

- Código-fonte **só** em `server/`, `client/` e `launcher/` (lançador em C#).
- `build_pacotes.bat` monta `1_PROFESSOR` e `2_ALUNO` (precisa de Python 3.12 + internet para baixar dependências). Preserva as pastas `dados`.
- `python_app/` é o Python embutido usado como modelo.
- `_antigo/` guarda as versões e sobras antigas; pode apagar quando quiser.
- O painel funciona 100% offline (Tailwind em `server/static/vendor`).
- Testes: `python -m unittest discover -s tests -v`.

## 🎓 Congelamento do sistema (UWF)

Veja `congelamento/GUIA_CONGELAMENTO_LABORATORIO.md` (também copiado em `2_ALUNO\congelamento`).

## 🧰 Ferramentas do painel

- **Turmas:** o seletor "Turma" (acima dos computadores) filtra a grade e faz os botões do topo (bloquear, aviso, arquivo, site, energia) agirem **só naquela turma**. A turma vem do cadastro do aluno que fez login no PC.
- **Bloquear** com mensagem personalizada (prontas: explicação, prova, intervalo, fim da aula) e **timer**: "liberar automaticamente em 5, 10, 15... minutos". O PC do aluno mostra a contagem regressiva e se libera sozinho, mesmo se a rede cair.
- **Regras** (aba própria): **programas bloqueados** (fechados assim que abrem, ex.: `RobloxPlayerBeta.exe`) e **sites bloqueados** (palavra no título da aba, ex.: `youtube`; a aba é fechada). Valem para todos os PCs, ficam salvas no PC do aluno (funcionam sem rede) e cada tentativa aparece em "Ocorrências recentes". Programas do sistema e o próprio GestorLab nunca são fechados.
  - Limitação: o bloqueio de site olha o **título** da aba, não o endereço. Sites com título sem a palavra (ou abertos em navegador desconhecido) passam. Não substitui o filtro de conteúdo da rede da escola.
- **Abrir Site** em todos os PCs ou em um só (botão no topo e na tela ampliada). Só endereços http/https.
- **Salvar Print** da tela de um aluno (na tela ampliada).
- **Importar Planilha** de alunos (CSV do Excel, separado por `;`): colunas `Matrícula;Nome;Turma;Senha`. Senha em branco = a própria matrícula. **Exportar** baixa a lista atual.

## 📊 Presença e desempenho

- A aba **Presença** do painel lista quem usou cada computador (entrada, saída e duração), com filtro por data e exportação CSV (abre no Excel).
- Se o computador do professor for desligado com alunos conectados, a saída fica registrada no último minuto em que o servidor estava ligado (antes ficava com duração zero).
- Para laboratórios grandes: o agente envia telas pequenas (2 FPS), **não reenvia tela parada** e **para de enviar quando nenhum painel está aberto**. Ao abrir um computador em tela cheia ele sobe a qualidade só naquele PC.
- Se a rede cair, os agentes reconectam com espera crescente e atraso aleatório, para não sobrecarregar o servidor quando voltar.
