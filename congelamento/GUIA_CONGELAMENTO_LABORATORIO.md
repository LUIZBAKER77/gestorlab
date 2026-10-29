# ❄️ Guia de Congelamento e Restauração Automática do Laboratório

Este guia orienta como configurar a **Restauração Automática ao Reiniciar** nos computadores dos alunos do laboratório escolar, garantindo que qualquer arquivo criado, vírus baixado, programa instalado ou alteração feita pelos alunos seja **100% descartada a cada reinicialização**.

---

## 📌 Método 1: UWF (Unified Write Filter) — 100% Nativo do Windows 10/11 Pro

O **Unified Write Filter (UWF)** é um recurso oficial embutido no Windows 10 Pro, Enterprise e Education pela Microsoft. Ele intercepta todas as gravações no disco e as armazena em uma camada temporária na memória RAM (Overlay). Ao reiniciar o computador, o cache da RAM é limpo e o sistema volta exatamente ao ponto original.

### 🚀 Vantagens:
- **Zero programas de terceiros:** Não precisa instalar nada, é oficial da Microsoft.
- **Não expira:** Vitalício e gratuito em edições Pro/Enterprise.
- **Desempenho máximo:** Gravações vão para a RAM, tornando o PC mais rápido e poupando a vida útil do SSD.

### 🛠️ Como Ativar:
1. No computador do aluno, vá até a pasta `congelamento/`.
2. Clique com o botão direito em **`ativar_congelamento_uwf.bat`** e selecione **"Executar como Administrador"**.
3. O script ativará o recurso, protegerá o disco `C:` e solicitará reiniciar.
4. Reinicie o computador. **Pronto! O computador agora está 100% congelado.**

### 🔧 Como Desativar para Fazer Manutenção (Instalar Novos Programas):
1. Execute **`desativar_congelamento_uwf.bat`** como Administrador.
2. Reinicie o computador.
3. Faça as atualizações ou instale os programas necessários.
4. Execute **`ativar_congelamento_uwf.bat`** novamente como Administrador e reinicie.

### 🔍 Como Verificar o Status:
Execute **`status_congelamento_uwf.bat`** para ver se a unidade `C:` está protegida e o consumo de memória do filtro.

---

## 📌 Método 2: Reboot Restore Rx (Alternativa com Interface Gráfica)

Se preferir uma ferramenta com instalador gráfico simples ou caso utilize máquinas com Windows 10 Home (que não possuem UWF):

1. **Download:** Baixe o **Reboot Restore Rx Freeware** no site oficial:
   `https://horizondatasys.com/reboot-restore-rx-freeware/`
2. **Instalação:** Execute o instalador `setup.exe` na máquina do aluno e selecione a partição `C:`.
3. **Reinicie:** Uma vez instalado, um ícone de escudo aparecerá na bandeja do sistema ao lado do relógio.
4. **Funcionamento:**
   - **Ícone Verde:** O sistema está congelado. Qualquer alteração é apagada no reboot.
   - **Modo Manutenção:** Clique com o botão direito no ícone do escudo, digite a senha e escolha "Disable" para instalar programas. Depois escolha "Enable" para congelar novamente.

---

## 📌 Método 3: Manter os Arquivos do Agente GestorLab Salvos

Se o computador estiver congelado com o UWF e você quiser que certas pastas específicas continuem salvando alterações (como exclusões de filtro):
```cmd
uwfmgr file add-exclusion "C:\caminho\da\pasta"
```
No caso do GestorLab, como o executável `agente_aluno.exe` conecta dinamicamente ao professor e não depende de banco de dados local pesado, mesmo com o computador 100% congelado ele continuará iniciando normalmente com o Windows e se conectando ao professor!
