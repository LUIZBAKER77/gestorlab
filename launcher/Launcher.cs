// Lançador do GestorLab: inicia o Python embutido (pasta app\), reinicia se cair,
// registra o início automático com o Windows e garante uma única instância.
// Compilar com:  csc /target:winexe /define:PROFESSOR  (ou /define:ALUNO)  Launcher.cs
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

static class Launcher
{
#if PROFESSOR
    const string Role = "Professor";
    const string RunValue = "GestorLabProfessor";
    const string Script = "main.py";
    const string LocalFolder = @"C:\GestorLabProfessor";
#else
    const string Role = "Aluno";
    const string RunValue = "GestorLabAgent";
    const string Script = "agent.py";
    const string LocalFolder = @"C:\GestorLab";
#endif
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";

    static string baseDir, dataDir;

    [STAThread]
    static int Main(string[] args)
    {
        baseDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        dataDir = Path.Combine(baseDir, "dados");
        Directory.CreateDirectory(dataDir);
        string manualFlag = Path.Combine(dataDir, "inicio_manual.txt");
        string self = Process.GetCurrentProcess().MainModule.FileName;

        if (Has(args, "--remover-inicio"))
        {
            File.WriteAllText(manualFlag, "Início automático desativado. Apague este arquivo para reativar.");
            SetRun(null);
            Info("Início automático com o Windows desativado.");
            return 0;
        }
        if (Has(args, "--instalar-inicio"))
        {
            if (File.Exists(manualFlag)) File.Delete(manualFlag);
            SetRun("\"" + self + "\" --autostart");
            Info("Início automático com o Windows ativado.");
            return 0;
        }

        bool autostart = Has(args, "--autostart");

        // Rodando de um disco de rede: o Windows pede permissão ("Aviso de segurança") a cada início
        // automático e o programa depende da rede estar pronta. Instala uma cópia no disco do PC e
        // continua de lá; o início automático passa a apontar para a cópia local.
        if (IsNetworkPath(baseDir) && !Has(args, "--sem-copia"))
        {
            Mutex running;
            if (Mutex.TryOpenExisting("Global\\GestorLab_" + Role, out running))
            {
                running.Dispose();   // a cópia local já está rodando: não mexe nos arquivos em uso
#if PROFESSOR
                OpenBrowser();
#endif
                return 0;
            }
            string localExe = InstallLocally(baseDir, Path.GetFileName(self), autostart);
            if (localExe != null)
            {
                try
                {
                    Process.Start(new ProcessStartInfo(localExe, string.Join(" ", args))
                    {
                        UseShellExecute = false,
                        WorkingDirectory = Path.GetDirectoryName(localExe),
                    });
                    return 0;
                }
                catch (Exception ex) { Log("Falha ao iniciar a cópia local: " + ex.Message); }
            }
            // Cópia impossível (sem permissão, disco cheio...): segue rodando pela rede mesmo.
        }

        bool createdNew;
        using (var mutex = new Mutex(true, "Global\\GestorLab_" + Role, out createdNew))
        {
            if (!createdNew)
            {
#if PROFESSOR
                OpenBrowser();   // já está rodando: só abre o painel
#endif
                return 0;
            }

            if (!File.Exists(manualFlag)) SetRun("\"" + self + "\" --autostart");

            string python = Path.Combine(baseDir, @"app\python\pythonw.exe");
            string script = Path.Combine(baseDir, @"app\code\" + Script);
            if (!File.Exists(python) || !File.Exists(script))
            {
                MessageBox.Show("Arquivos do programa não encontrados na pasta 'app'.\nCopie a pasta inteira, não só o .exe.",
                                "GestorLab", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }

            IntPtr job = CreateKillOnCloseJob();
            int quickFailures = 0;
            bool firstRun = true;

            while (true)
            {
                var psi = new ProcessStartInfo(python, "\"" + script + "\"")
                {
                    WorkingDirectory = Path.GetDirectoryName(script),
                    UseShellExecute = false,
                    CreateNoWindow = true,
                };
                psi.EnvironmentVariables["GESTORLAB_DATA"] = dataDir;
                psi.EnvironmentVariables["GESTORLAB_LAUNCHER"] = self;
                // Navegador só na abertura manual (não no login do Windows nem em reinícios).
                psi.EnvironmentVariables["GESTORLAB_BROWSER"] = (firstRun && !autostart) ? "1" : "0";
                firstRun = false;

                DateTime started = DateTime.Now;
                try
                {
                    using (Process p = Process.Start(psi))
                    {
                        if (job != IntPtr.Zero) AssignProcessToJobObject(job, p.Handle);
                        p.WaitForExit();
                    }
                }
                catch (Exception ex)
                {
                    Log("Falha ao iniciar o Python: " + ex.Message);
                }

                // Reinicia sempre; se cair repetidamente logo ao iniciar, espera mais.
                quickFailures = (DateTime.Now - started).TotalSeconds < 10 ? quickFailures + 1 : 0;
                Thread.Sleep(quickFailures >= 5 ? 30000 : 3000);
            }
        }
    }

    static bool IsNetworkPath(string dir)
    {
        if (dir.StartsWith("\\\\")) return true;   // \\servidor\pasta
        try { return new DriveInfo(Path.GetPathRoot(dir)).DriveType == DriveType.Network; }   // Z:\ mapeado
        catch { return false; }
    }

    static int RunHidden(string file, string arguments)
    {
        var psi = new ProcessStartInfo(file, arguments) { UseShellExecute = false, CreateNoWindow = true };
        using (Process p = Process.Start(psi))
        {
            p.WaitForExit();
            return p.ExitCode;
        }
    }

    // Copia o programa para o disco local (a pasta "dados" local nunca é sobrescrita) e devolve o .exe de lá.
    static string InstallLocally(string src, string exeName, bool silent)
    {
        try
        {
            string dst = LocalFolder;
            Directory.CreateDirectory(dst);
            // Todos os usuários do PC precisam poder gravar logs e configurações (S-1-5-32-545 = "Usuários").
            try { RunHidden("icacls", "\"" + dst + "\" /grant *S-1-5-32-545:(OI)(CI)M /C /Q"); } catch { }

            // robocopy: códigos 0 a 7 = sucesso.
            if (RunHidden("robocopy", "\"" + src + "\" \"" + dst + "\" /E /XD dados /R:2 /W:2 /NFL /NDL /NJH /NJS /NP") >= 8)
            {
                Log("robocopy falhou ao copiar para " + dst);
                return null;
            }
            string srcData = Path.Combine(src, "dados"), dstData = Path.Combine(dst, "dados");
            if (Directory.Exists(srcData) && !Directory.Exists(dstData))
                RunHidden("robocopy", "\"" + srcData + "\" \"" + dstData + "\" /E /R:2 /W:2 /NFL /NDL /NJH /NJS /NP");

            string localExe = Path.Combine(dst, exeName);
            if (!File.Exists(localExe)) return null;
            if (!silent)
                MessageBox.Show("O GestorLab foi instalado em " + dst + "\nIniciará sozinho com o Windows, sem pedir permissão.\n" +
                                "Você já pode fechar a pasta de rede.", "GestorLab", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return localExe;
        }
        catch (Exception ex)
        {
            Log("Instalação local: " + ex.Message);
            return null;
        }
    }

    static bool Has(string[] args, string flag)
    {
        foreach (string a in args) if (string.Equals(a, flag, StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    static void SetRun(string command)
    {
        try
        {
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey(RunKey, true))
            {
                if (k == null) return;
                if (command == null) k.DeleteValue(RunValue, false);
                else k.SetValue(RunValue, command);
            }
        }
        catch (Exception ex) { Log("Registro: " + ex.Message); }
    }

#if PROFESSOR
    static void OpenBrowser()
    {
        try { Process.Start(new ProcessStartInfo("http://localhost:" + ReadPort()) { UseShellExecute = true }); }
        catch { }
    }

    // Respeita a porta configurada em dados\server_config.json (antes era sempre 8000).
    static int ReadPort()
    {
        try
        {
            string cfg = File.ReadAllText(Path.Combine(dataDir, "server_config.json"));
            var m = System.Text.RegularExpressions.Regex.Match(cfg, "\"port\"\\s*:\\s*(\\d+)");
            if (m.Success) return int.Parse(m.Groups[1].Value);
        }
        catch { }
        return 8000;
    }
#endif

    static void Info(string msg) { MessageBox.Show(msg, "GestorLab", MessageBoxButtons.OK, MessageBoxIcon.Information); }

    static void Log(string msg)
    {
        try { File.AppendAllText(Path.Combine(dataDir, "lancador.log"), DateTime.Now.ToString("s") + " " + msg + "\r\n"); }
        catch { }
    }

    // Job object: se o lançador for encerrado, o Python filho também é (sem processo órfão).
    [StructLayout(LayoutKind.Sequential)]
    struct BASIC_LIMIT
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IO_COUNTERS { public ulong a, b, c, d, e, f; }
    [StructLayout(LayoutKind.Sequential)]
    struct EXTENDED_LIMIT
    {
        public BASIC_LIMIT Basic;
        public IO_COUNTERS Io;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll")] static extern IntPtr CreateJobObject(IntPtr attrs, string name);
    [DllImport("kernel32.dll")] static extern bool SetInformationJobObject(IntPtr job, int cls, ref EXTENDED_LIMIT info, int size);
    [DllImport("kernel32.dll")] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    static IntPtr CreateKillOnCloseJob()
    {
        try
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            var info = new EXTENDED_LIMIT();
            info.Basic.LimitFlags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (!SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(typeof(EXTENDED_LIMIT)))) return IntPtr.Zero;
            return job;
        }
        catch { return IntPtr.Zero; }
    }
}
