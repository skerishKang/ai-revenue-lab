// #5573 follow-up: the one-click PC connect, as a file a person double-clicks.
//
// The install file this replaces asked the PC to run PowerShell and to type a
// pairing code. This one is the same lane with two things taken away: nothing is
// typed, because the account's own tag arrives inside the downloaded file, and no
// shell is involved, because the file IS the program.
//
// What it does, in order: read the tag out of its own trailing bytes, ask for
// administrator approval once, look up the fixed drives this PC really has,
// download the deployment's own agent installer over TLS 1.2 at minimum, put it in
// a folder of the product's own, and install the service from there with the name
// the server pairs on. An agent that is already there is stopped, replaced under the
// same service name and started again - never registered a second time.
//
// The install switch was measured, not assumed. This MeshCentral build's own help
// says "-install: install the service from this location" and "-fullinstall: copy
// agent into program files, install and launch", and on the tagged Windows agent of
// 2026-10-28 -fullinstall exited 0 and registered nothing while -install did. So the
// copy is this program's job: -install leaves the service pointing at whatever
// folder it ran from, and a service whose binary sits in a temp file is a service
// that dies at the next restart of the PC.
//
// What it never does: it stores nothing (the tag and the link live in this
// process), it asks no account password, and it runs no command line the browser
// assembled. The installer link is refused unless it is plain https with no
// credentials, and the bytes it fetches are checked for an executable header
// before anything is allowed to run as SYSTEM.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

// The names Windows shows even without a signature. The native version resource is
// written by the build, and these are the same words inside the managed metadata, so
// neither half of the file can call this program something else.
[assembly: AssemblyTitle("padiem-pc-connect")]
[assembly: AssemblyDescription("PADIEM PC 연결")]
[assembly: AssemblyCompany("PADIEM")]
[assembly: AssemblyProduct("PADIEM")]
[assembly: AssemblyCopyright("PADIEM")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace Padiem.Connect
{
    internal static class PadiemPcConnect
    {
        // ---- what the downloaded file already knows ----------------------
        //
        // The Chat route writes these lines after the program bytes. Windows runs
        // an executable regardless of what follows it, so the tag travels with the
        // file instead of in a second file, a registry value, or something typed.
        const string TrailerMarker = "PADIEMTRAILER:PADIEM-PC-CONNECT-1";
        const string KeyTag = "PADIEMTAG";
        const string KeyAgentUrl = "PADIEMURL";
        const string KeyChatOrigin = "PADIEMCHAT";
        const int TrailerWindowBytes = 4096;

        const string HandoffPath = "/api/pc/pairings/handoff";
        const string AgentServiceName = "Mesh Agent";
        const string AgentServiceKey =
            "SYSTEM\\CurrentControlSet\\Services\\Mesh Agent";
        const string AgentFileName = "MeshAgent.exe";
        const string DurableFolder = "PADIEM";
        const int InstallerTimeoutMilliseconds = 180000;
        const int HandoffTimeoutMilliseconds = 30000;
        const int MaximumRedirects = 4;
        const int MaximumResponseChars = 65536;

        static readonly string AgentInstallDirectory =
            Environment.ExpandEnvironmentVariables("%ProgramFiles(x86)%") + "\\Mesh Services";

        static readonly Regex PairingCode =
            new Regex("^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{12}$", RegexOptions.CultureInvariant);
        static readonly Regex InstallTag =
            new Regex("^[A-Za-z0-9_-]{1,64}$", RegexOptions.CultureInvariant);
        static readonly Regex MachineWord =
            new Regex("^[A-Za-z0-9._-]{1,64}$", RegexOptions.CultureInvariant);

        const int ExitOk = 0;
        const int ExitUsage = 2;
        const int ExitNotReady = 3;
        const int ExitCodeRejected = 4;
        const int ExitElevationRefused = 5;
        const int ExitInstallerFailed = 6;
        const int ExitNothingToConnect = 7;
        const int ExitDownloadUnusable = 8;
        const int ExitCrashed = 9;

        static readonly Dictionary<string, string> Trailer = ReadOwnTrailer();

        static int Main(string[] arguments)
        {
            Options options;
            string refusal = Options.Parse(arguments, out options);
            if (refusal != null)
            {
                Say(refusal);
                return ExitUsage;
            }
            if (options.Help)
            {
                Usage();
                return ExitOk;
            }
            try
            {
                // The sentences this program says are Korean, and a console still on
                // the machine's own code page turns them into question marks. UTF-8
                // output, refused quietly when there is no console to set it on.
                Console.OutputEncoding = new UTF8Encoding(false);
                EnforceTransportSecurity();
                if (options.Check)
                {
                    return Report(options);
                }
                if (!options.DryRun && !IsAdministrator())
                {
                    Say("관리자 권한 승인 창이 나타나면 [예]를 눌러 주세요. 설치 프로그램은 관리자 권한으로만 동작합니다.");
                    return RelaunchElevated(arguments);
                }
                return Connect(options);
            }
            catch (Exception error)
            {
                // The type name only: a message can carry the URL we were fetching,
                // and a screen a person photographs is not where that belongs.
                Say("PC 연결을 마치지 못했습니다 (" + error.GetType().Name + "). 잠시 후 다시 시도해 주세요.");
                return ExitCrashed;
            }
            finally
            {
                PauseIfDoubleClicked(options);
            }
        }

        // ---- the walk ----------------------------------------------------

        static int Connect(Options options)
        {
            string tag = Value(KeyTag);
            string agentUrl = CleanHttps(Value(KeyAgentUrl));
            string chatOrigin = CleanHttps(Value(KeyChatOrigin));
            if (string.IsNullOrEmpty(tag))
            {
                // No tag inside the file: the code the account showed the person is
                // the only way in, and the server hands back the same two values.
                if (string.IsNullOrEmpty(chatOrigin))
                {
                    chatOrigin = CleanHttps(options.Origin);
                }
                if (string.IsNullOrEmpty(chatOrigin))
                {
                    Say("이 파일에는 연결 표식이 들어 있지 않고, PADIEM 주소도 알려 주지 않았습니다. 브라우저의 '이 PC 연결'에서 내려받은 파일을 사용하세요.");
                    return ExitNothingToConnect;
                }
                string code = string.IsNullOrEmpty(options.Code) ? ReadCode() : options.Code;
                if (!PairingCode.IsMatch(NormalizeCode(code)))
                {
                    Say("연결 코드 형식이 올바르지 않습니다. 코드를 다시 확인하거나 새 코드를 발급하세요.");
                    return ExitCodeRejected;
                }
                string handoff = PostHandoff(chatOrigin, NormalizeCode(code));
                if (handoff == null)
                {
                    Say("서버가 아직 PC 연결 준비 중입니다. 잠시 후 다시 실행하세요.");
                    return ExitNotReady;
                }
                tag = JsonValue(handoff, KeyTag);
                if (!InstallTag.IsMatch(tag))
                {
                    Say("이 코드는 사용할 수 없습니다(만료되었거나 이미 쓰였습니다). 새 코드로 다시 시도하세요.");
                    return ExitCodeRejected;
                }
                agentUrl = CleanHttps(JsonValue(handoff, KeyAgentUrl));
            }

            bool installed = AgentAlreadyInstalled();
            if (string.IsNullOrEmpty(agentUrl))
            {
                // The tag is good and the account exists; only the download link is
                // not configured on this deployment yet. An installed agent still
                // waits for the server's own confirmation, so this is not a failure.
                Say(installed ? "에이전트가 이미 설치되어 있습니다. 서버 확인을 기다립니다."
                              : "이 PC에 에이전트가 아직 없고 서버가 설치 링크를 아직 내려주지 않았습니다. 잠시 후 다시 실행하세요.");
                return ExitOk;
            }
            if (installed)
            {
                Say("이 PC에는 에이전트가 이미 설치되어 있습니다. 같은 서비스 이름으로 갱신 설치합니다(중복 서비스 없음).");
            }
            string name = AgentName(tag, FixedDriveLetters(), Environment.MachineName);
            string durable = DurableAgentPath();
            string installerArguments = "-install --agentName=\"" + name + "\"";
            if (options.DryRun)
            {
                Say("점검 실행: 설치 프로그램은 실행하지 않았습니다.");
                Say("설치 대상 " + agentUrl);
                Say("설치 위치 " + durable);
                Say("실행 명령 " + AgentFileName + " " + installerArguments);
                Say("에이전트 이름 " + name);
                return ExitOk;
            }
            string temp = Path.Combine(Path.GetTempPath(),
                "padiem-agent-" + Guid.NewGuid().ToString("N") + ".exe");
            try
            {
                int downloaded = Download(agentUrl, temp);
                if (downloaded <= 0)
                {
                    Say("설치 프로그램을 내려받지 못했습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.");
                    return ExitDownloadUnusable;
                }
                // Stop the service through the binary it was registered with, so an
                // update over a running agent does not fail on a locked file. A PC that
                // never had the agent has nothing to stop, and that is not a failure.
                if (installed)
                {
                    string running = RegisteredAgentPath();
                    if (running != null && !running.Equals(durable, StringComparison.OrdinalIgnoreCase))
                    {
                        RunQuiet(running, "-stop");
                    }
                }
                if (!Place(temp, durable))
                {
                    Say("에이전트를 놓을 폴더를 만들 수 없습니다. 다른 프로그램이 사용 중인지 확인해 주세요.");
                    return ExitInstallerFailed;
                }
                if (!StartInstaller(durable, installerArguments))
                {
                    Say("PC 연결 프로그램을 실행하지 못했습니다. 잠시 후 다시 시도해 주세요.");
                    return ExitInstallerFailed;
                }
                // -install registers; it does not launch. Saying so once, here, is what
                // makes a fresh PC answer the server's first call instead of waiting for
                // the next restart of Windows.
                RunQuiet(durable, "-start");
            }
            finally
            {
                try { File.Delete(temp); }
                catch (Exception) { }
            }
            Say("연결 진행 중 - 서버가 이 PC를 확인하면 PADIEM의 '내 PC 연결'에 자동으로 나타납니다.");
            Say("연결 표식 " + tag);
            Say("에이전트 " + durable);
            return ExitOk;
        }

        static string DurableAgentPath()
        {
            // Program Files, not Temp: -install leaves the service pointing at whatever
            // folder the agent ran from, so a temp download would become a service that
            // cannot start after the file is cleaned up.
            return Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.ProgramFiles), DurableFolder, AgentFileName);
        }

        static string RegisteredAgentPath()
        {
            // The service's own recorded binary. Reading a registry value is allowed
            // without elevation and says exactly which file is in use.
            try
            {
                using (Microsoft.Win32.RegistryKey key =
                    Microsoft.Win32.Registry.LocalMachine.OpenSubKey(AgentServiceKey))
                {
                    if (key == null)
                    {
                        return null;
                    }
                    object value = key.GetValue("ImagePath");
                    string text = value == null
                        ? null : Convert.ToString(value, CultureInfo.InvariantCulture);
                    if (string.IsNullOrEmpty(text))
                    {
                        return null;
                    }
                    text = text.Trim();
                    if (text.StartsWith("\"", StringComparison.Ordinal))
                    {
                        int closing = text.IndexOf('"', 1);
                        return closing > 1 ? text.Substring(1, closing - 1) : null;
                    }
                    int space = text.IndexOf(' ');
                    return space < 0 ? text : text.Substring(0, space);
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        static bool Place(string source, string target)
        {
            // The stop above is asynchronous, so the first copy over a just-stopped
            // service can still see the file held; three short waits is the whole retry,
            // and a folder that will not take the agent is a refusal the person is told.
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                for (int attempt = 0; attempt < 3; attempt++)
                {
                    try
                    {
                        File.Copy(source, target, true);
                        return true;
                    }
                    catch (IOException)
                    {
                        Thread.Sleep(1000);
                    }
                }
                return false;
            }
            catch (Exception)
            {
                return false;
            }
        }

        static int Report(Options options)
        {
            // --check is the whole automated surface: offline, un-elevated, and it
            // installs nothing. It answers one question - does this file carry a
            // usable tag and link, and what would the run do with them.
            string tag = Value(KeyTag);
            string agentUrl = CleanHttps(Value(KeyAgentUrl));
            bool usable = !string.IsNullOrEmpty(tag) && !string.IsNullOrEmpty(agentUrl);
            Console.WriteLine(usable
                ? "CONNECT_EXE_CHECK=PASS"
                : (string.IsNullOrEmpty(tag) ? "CONNECT_EXE_CHECK=NO_TRAILER" : "CONNECT_EXE_CHECK=URL_UNUSABLE"));
            Console.WriteLine("CONNECT_EXE_CHECK_TAG=" + tag);
            Console.WriteLine("CONNECT_EXE_CHECK_URL_PRESENT=" + (string.IsNullOrEmpty(agentUrl) ? "0" : "1"));
            Console.WriteLine("CONNECT_EXE_CHECK_DRIVES=" + string.Join(" ", FixedDriveLetters()));
            Console.WriteLine("CONNECT_EXE_CHECK_SERVICE_INSTALLED=" + (AgentAlreadyInstalled() ? "1" : "0"));
            Console.WriteLine("CONNECT_EXE_CHECK_AGENT_TARGET=" + DurableAgentPath());
            string registered = RegisteredAgentPath();
            Console.WriteLine("CONNECT_EXE_CHECK_SERVICE_PATH=" + (registered ?? ""));
            Console.WriteLine("CONNECT_EXE_CHECK_ELEVATED=" + (IsAdministrator() ? "1" : "0"));
            Console.WriteLine("CONNECT_EXE_CHECK_TLS=" + TlsSummary());
            if (!string.IsNullOrEmpty(tag))
            {
                Console.WriteLine("CONNECT_EXE_CHECK_NAME=" +
                    AgentName(tag, FixedDriveLetters(), Environment.MachineName));
            }
            return ExitOk;
        }

        // ---- the four facts the installer needs --------------------------

        static string AgentName(string tag, List<string> letters, string machine)
        {
            // The name the agent reports is what the server reads the pairing from:
            // the tag decides the account, the bracketed letters are this PC's own
            // drives, and the trailing word is the name Windows gave the machine.
            // The grammar is the one the install file already used, unchanged.
            string word = machine == null ? "" : machine.ToUpperInvariant();
            if (!MachineWord.IsMatch(word))
            {
                word = "";
            }
            string built = tag;
            if (letters.Count > 0)
            {
                built = built + " [" + string.Join(" ", letters.ToArray()) + "]";
            }
            if (word.Length > 0)
            {
                built = built + " " + word;
            }
            return built;
        }

        static List<string> FixedDriveLetters()
        {
            // A linked PC works over its whole local drives by default, so the PC
            // names the fixed drives it actually has. Mapped network shares report
            // as Network and stay out; a failed query names nothing at all.
            List<string> letters = new List<string>();
            try
            {
                DriveInfo[] drives = DriveInfo.GetDrives();
                for (int index = 0; index < drives.Length; index++)
                {
                    try
                    {
                        if (drives[index].DriveType != DriveType.Fixed)
                        {
                            continue;
                        }
                        string letter = drives[index].Name.TrimEnd('\\').ToUpperInvariant();
                        // One bare letter, not "C:": the server reads the bracketed
                        // group as single letters, and the install file has always
                        // written it that way. A colon here would report no drives
                        // at all, and the link would arrive with nothing granted.
                        if (letter.Length == 2 && letter[1] == ':')
                        {
                            letter = letter.Substring(0, 1);
                        }
                        else
                        {
                            continue;
                        }
                        if (!letters.Contains(letter))
                        {
                            letters.Add(letter);
                        }
                    }
                    catch (Exception) { }
                }
            }
            catch (Exception) { }
            letters.Sort(StringComparer.Ordinal);
            return letters;
        }

        static bool AgentAlreadyInstalled()
        {
            // Two independent looks, because either alone lies: the service can be
            // registered with its binary already gone, and the folder can hold a
            // copied agent that was never installed. Installing over an existing
            // agent is what the re-run means, and the same service name keeps it one
            // service rather than two.
            if (ServiceExists(AgentServiceName))
            {
                return true;
            }
            try
            {
                if (!Directory.Exists(AgentInstallDirectory))
                {
                    return false;
                }
                string[] files = Directory.GetFiles(AgentInstallDirectory, "*.exe");
                return files.Length > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        // ---- transport --------------------------------------------------

        static void EnforceTransportSecurity()
        {
            // The default protocol on a machine that has not been configured can be
            // as low as TLS 1.0, and this program downloads a binary it will run as
            // a service. TLS 1.2 is the floor; 1.3 is offered only when the operating
            // system's own Schannel has it (Windows 10 1903 and newer), because
            // naming a protocol the stack cannot speak fails the request outright.
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            try
            {
                // Schannel grew TLS 1.3 in Windows 10 1903 (build 18362). Naming a
                // protocol the stack cannot speak fails the request outright, so it is
                // offered only where it exists - and the manifest declares the
                // operating systems this program supports, which is what keeps
                // OSVersion honest enough to read that build from.
                Version running = Environment.OSVersion.Version;
                if (running.Major >= 10 && running.Build >= 18362)
                {
                    ServicePointManager.SecurityProtocol |= (SecurityProtocolType)12288;
                }
            }
            catch (Exception) { }
        }

        static string TlsSummary()
        {
            return "1.2+" + ((((int)ServicePointManager.SecurityProtocol & 12288) == 12288) ? "1.3" : "");
        }

        static int Download(string url, string target)
        {
            // No automatic redirects: every hop is re-checked here, so a link that
            // tried to walk off to plain http or to a host of somebody else's
            // choosing is refused before a byte of it is saved.
            string current = url;
            for (int hop = 0; hop <= MaximumRedirects; hop++)
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(current);
                request.Method = "GET";
                request.AllowAutoRedirect = false;
                request.Timeout = InstallerTimeoutMilliseconds;
                request.ReadWriteTimeout = InstallerTimeoutMilliseconds;
                request.UserAgent = "PADIEM-PC-CONNECT/1.0";
                HttpWebResponse response = null;
                try
                {
                    response = (HttpWebResponse)request.GetResponse();
                    if (response.StatusCode == HttpStatusCode.Moved
                        || response.StatusCode == HttpStatusCode.Found
                        || response.StatusCode == HttpStatusCode.Redirect
                        || response.StatusCode == HttpStatusCode.TemporaryRedirect)
                    {
                        string next = response.Headers["Location"];
                        current = CleanHttps(next);
                        if (current == null)
                        {
                            return -1;
                        }
                        continue;
                    }
                    if ((int)response.StatusCode < 200 || (int)response.StatusCode > 299)
                    {
                        return -1;
                    }
                    int written = 0;
                    using (Stream source = response.GetResponseStream())
                    using (FileStream sink = File.Create(target))
                    {
                        byte[] buffer = new byte[81920];
                        int total = 0;
                        int read = source.Read(buffer, 0, buffer.Length);
                        while (read > 0)
                        {
                            sink.Write(buffer, 0, read);
                            total += read;
                            read = source.Read(buffer, 0, buffer.Length);
                        }
                        if (total < 2)
                        {
                            return -1;
                        }
                        sink.Flush();
                        written = total;
                    }
                    byte[] head = new byte[2];
                    using (FileStream check = File.OpenRead(target))
                    {
                        if (check.Read(head, 0, 2) != 2)
                        {
                            return -1;
                        }
                    }
                    // What we are about to run as a service has to be an executable,
                    // not an error page that a proxy saved under a .exe name.
                    if (head[0] != 0x4D || head[1] != 0x5A)
                    {
                        return -1;
                    }
                    return written;
                }
                catch (WebException)
                {
                    return -1;
                }
                finally
                {
                    if (response != null)
                    {
                        response.Close();
                    }
                }
            }
            return -1;
        }

        static string PostHandoff(string origin, string code)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(origin + HandoffPath);
            request.Method = "POST";
            request.ContentType = "application/json";
            request.Accept = "application/json";
            request.Timeout = HandoffTimeoutMilliseconds;
            request.UserAgent = "PADIEM-PC-CONNECT/1.0";
            byte[] body = Encoding.UTF8.GetBytes("{\"code\":\"" + code + "\"}");
            request.ContentLength = body.Length;
            try
            {
                using (Stream outlet = request.GetRequestStream())
                {
                    outlet.Write(body, 0, body.Length);
                }
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                {
                    return Limited(reader.ReadToEnd());
                }
            }
            catch (WebException failure)
            {
                HttpWebResponse answered = failure.Response as HttpWebResponse;
                if (answered == null)
                {
                    return null;
                }
                try
                {
                    using (StreamReader reader = new StreamReader(answered.GetResponseStream(), Encoding.UTF8))
                    {
                        return Limited(reader.ReadToEnd());
                    }
                }
                catch (Exception)
                {
                    return null;
                }
                finally
                {
                    answered.Close();
                }
            }
        }

        static string Limited(string text)
        {
            if (text == null)
            {
                return null;
            }
            return text.Length <= MaximumResponseChars ? text : text.Substring(0, MaximumResponseChars);
        }

        static string JsonValue(string json, string key)
        {
            // "install_tag": "pd-abc", "agent_url": null - the two values this
            // program needs are flat strings, so a quoted-string reader is enough
            // and no JSON library travels in the file.
            if (json == null)
            {
                return "";
            }
            string needle = "\"" + key + "\"";
            int at = json.IndexOf(needle, StringComparison.Ordinal);
            if (at < 0)
            {
                return "";
            }
            at = json.IndexOf(':', at + needle.Length);
            if (at < 0)
            {
                return "";
            }
            int quote = json.IndexOf('"', at + 1);
            if (quote < 0)
            {
                return "";
            }
            StringBuilder value = new StringBuilder();
            for (int index = quote + 1; index < json.Length; index++)
            {
                char character = json[index];
                if (character == '"')
                {
                    break;
                }
                if (character == '\\' && index + 1 < json.Length)
                {
                    index += 1;
                    character = json[index];
                }
                value.Append(character);
            }
            return value.ToString();
        }

        static bool StartInstaller(string path, string arguments)
        {
            // -install registers the service from the folder this file sits in, and the
            // name the agent reports is what the server pairs the PC on. Passing the
            // arguments as a list, not a split string, is what lets an agent name with
            // spaces arrive intact.
            ProcessStartInfo start = new ProcessStartInfo(path, arguments);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            try
            {
                using (Process process = Process.Start(start))
                {
                    if (process == null)
                    {
                        return false;
                    }
                    process.WaitForExit();
                    return process.ExitCode == 0;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        static void RunQuiet(string path, string argument)
        {
            // -stop and -start are asked of the agent itself rather than of a shell:
            // this is the one program on the PC that knows its own service name, and a
            // PC that refuses to stop is still worth installing over.
            if (string.IsNullOrEmpty(path) || !File.Exists(path))
            {
                return;
            }
            try
            {
                ProcessStartInfo start = new ProcessStartInfo(path, argument);
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                using (Process process = Process.Start(start))
                {
                    if (process != null)
                    {
                        process.WaitForExit(15000);
                    }
                }
            }
            catch (Exception) { }
        }

        // ---- the file's own trailing bytes -------------------------------

        static Dictionary<string, string> ReadOwnTrailer()
        {
            Dictionary<string, string> found = new Dictionary<string, string>(StringComparer.Ordinal);
            try
            {
                string path = OwnPath();
                if (path == null)
                {
                    return found;
                }
                long length = new FileInfo(path).Length;
                int window = length < TrailerWindowBytes ? (int)length : TrailerWindowBytes;
                byte[] tail = new byte[window];
                using (FileStream source = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                {
                    source.Seek(length - window, SeekOrigin.Begin);
                    int read = 0;
                    while (read < window)
                    {
                        int step = source.Read(tail, read, window - read);
                        if (step <= 0)
                        {
                            break;
                        }
                        read += step;
                    }
                    if (read < window)
                    {
                        byte[] short_ = new byte[read];
                        Array.Copy(tail, short_, read);
                        tail = short_;
                    }
                }
                string text = Encoding.ASCII.GetString(tail);
                int marker = text.LastIndexOf(TrailerMarker, StringComparison.Ordinal);
                if (marker < 0)
                {
                    return found;
                }
                string[] lines = text.Substring(marker + TrailerMarker.Length).Split(new string[] { "\r\n" },
                    StringSplitOptions.RemoveEmptyEntries);
                for (int index = 0; index < lines.Length; index++)
                {
                    int colon = lines[index].IndexOf(':');
                    if (colon <= 0)
                    {
                        continue;
                    }
                    string key = lines[index].Substring(0, colon);
                    string value = lines[index].Substring(colon + 1).Trim();
                    if (!found.ContainsKey(key))
                    {
                        found[key] = value;
                    }
                }
            }
            catch (Exception)
            {
                return new Dictionary<string, string>(StringComparer.Ordinal);
            }
            return found;
        }

        static string Value(string key)
        {
            string value;
            return Trailer.TryGetValue(key, out value) ? value : "";
        }

        static string OwnPath()
        {
            try
            {
                return Process.GetCurrentProcess().MainModule.FileName;
            }
            catch (Exception)
            {
                try
                {
                    return System.Reflection.Assembly.GetExecutingAssembly().Location;
                }
                catch (Exception)
                {
                    return null;
                }
            }
        }

        // ---- validators -------------------------------------------------

        static string CleanHttps(string value)
        {
            // A plain https URL with a host and nothing that could carry credentials
            // or a second destination. This is the same wall the server puts up
            // before it writes the value, so a hand-edited file gets the same answer
            // a bad configuration would: nothing to fetch.
            if (value == null)
            {
                return null;
            }
            string text = value.Trim();
            if (text.Length == 0 || text.Length > 2048)
            {
                return null;
            }
            // '@' is forbidden only where it could mean credentials: the authority.
            // MeshCentral's own agent link carries '@' inside its meshid query
            // (…/meshagents?id=4&meshid=<node>@<server>), so refusing it anywhere was
            // the same as throwing away the deployment's installer - which is what
            // closed a first-ever connect on a clean PC with "서버가 설치 링크를 아직
            // 내려주지 않았습니다" while the server had handed one out.
            int schemeEnd = text.IndexOf("://", StringComparison.Ordinal);
            if (schemeEnd < 0)
            {
                return null;
            }
            int pathStart = text.IndexOf('/', schemeEnd + 3);
            string authority = pathStart < 0
                ? text.Substring(schemeEnd + 3)
                : text.Substring(schemeEnd + 3, pathStart - schemeEnd - 3);
            if (authority.IndexOf('@') >= 0 || authority.Length == 0)
            {
                return null;
            }
            for (int index = 0; index < text.Length; index++)
            {
                char character = text[index];
                if (character <= 32 || character == 127)
                {
                    return null;
                }
            }
            if (!text.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }
            Uri parsed;
            if (!Uri.TryCreate(text, UriKind.Absolute, out parsed))
            {
                return null;
            }
            if (!parsed.IsAbsoluteUri || parsed.Scheme != "https" || string.IsNullOrEmpty(parsed.Host))
            {
                return null;
            }
            if (parsed.UserInfo.Length > 0)
            {
                return null;
            }
            return text;
        }

        static string NormalizeCode(string value)
        {
            if (value == null)
            {
                return "";
            }
            StringBuilder kept = new StringBuilder();
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (character != ' ' && character != '\t' && character != '-' && character != '\r' && character != '\n')
                {
                    kept.Append(char.ToUpperInvariant(character));
                }
            }
            return kept.ToString();
        }

        // ---- elevation and the console -----------------------------------

        static bool IsAdministrator()
        {
            try
            {
                using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                {
                    return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        static int RelaunchElevated(string[] arguments)
        {
            string path = OwnPath();
            if (path == null)
            {
                return ExitElevationRefused;
            }
            ProcessStartInfo start = new ProcessStartInfo(path);
            start.Verb = "runas";
            start.UseShellExecute = true;
            StringBuilder kept = new StringBuilder();
            for (int index = 0; index < arguments.Length; index++)
            {
                if (arguments[index].StartsWith("-", StringComparison.Ordinal))
                {
                    // Only the switches this program understands travel into the
                    // elevated child; nothing a caller typed is passed through blind.
                    if (kept.Length > 0)
                    {
                        kept.Append(' ');
                    }
                    kept.Append(arguments[index]);
                    if ((arguments[index] == "--origin" || arguments[index] == "--code")
                        && index + 1 < arguments.Length)
                    {
                        kept.Append(" \"").Append(arguments[index + 1].Replace("\"", "\"\"")).Append('"');
                        index += 1;
                    }
                }
            }
            start.Arguments = kept.ToString();
            try
            {
                using (Process process = Process.Start(start))
                {
                    if (process == null)
                    {
                        return ExitElevationRefused;
                    }
                    process.WaitForExit();
                    return process.ExitCode;
                }
            }
            catch (Exception)
            {
                // The person pressed [아니요] on the approval window, or policy
                // refused it. Nothing was installed and nothing was left behind.
                Say("설치 권한이 거부되었습니다. 관리자 권한으로 다시 실행해 주세요.");
                return ExitElevationRefused;
            }
        }

        static string ReadCode()
        {
            // Read one key at a time and echo nothing: the code is the proof that
            // binds this PC to an account, and it does not belong in a console
            // buffer, a command line, or a shell history file.
            Console.Write("PADIEM에서 표시한 12자리 연결 코드를 입력하세요 (화면에 표시되지 않습니다): ");
            StringBuilder typed = new StringBuilder();
            while (true)
            {
                ConsoleKeyInfo key;
                try
                {
                    key = Console.ReadKey(true);
                }
                catch (Exception)
                {
                    Console.WriteLine();
                    return "";
                }
                if (key.Key == ConsoleKey.Enter)
                {
                    Console.WriteLine();
                    return typed.ToString();
                }
                if (key.Key == ConsoleKey.Backspace)
                {
                    if (typed.Length > 0)
                    {
                        typed.Remove(typed.Length - 1, 1);
                    }
                    continue;
                }
                if (key.Key == ConsoleKey.Escape)
                {
                    Console.WriteLine();
                    return "";
                }
                if (key.KeyChar >= 33 && key.KeyChar <= 126)
                {
                    typed.Append(key.KeyChar);
                }
            }
        }

        static void PauseIfDoubleClicked(Options options)
        {
            // A double-clicked console program would close its window the moment it
            // finished, which leaves the person with no answer on the screen. A
            // script or a check run never waits for a key.
            if (options.Check || options.DryRun || !options.Paused)
            {
                return;
            }
            try
            {
                if (Console.IsInputRedirected)
                {
                    return;
                }
                Console.WriteLine();
                Console.WriteLine("이 창을 닫으려면 Enter를 누르세요.");
                Console.ReadKey(true);
            }
            catch (Exception) { }
        }

        static void Say(string text)
        {
            try
            {
                Console.Out.WriteLine(text);
                Console.Out.Flush();
            }
            catch (Exception) { }
        }

        static void Usage()
        {
            Say("padiem-pc-connect.exe            이 PC를 PADIEM 계정에 연결합니다(더블클릭 한 번).");
            Say("  --check                        아무것도 설치하지 않고, 이 파일이 담은 정보만 표시합니다.");
            Say("  --dry-run                      실행할 내용만 보여 주고 멈춥니다.");
            Say("  --origin https://host         연결 코드만 입력받은 경우에 한할 PADIEM 주소.");
            Say("  --code XXXXXXXXXXXX           자동 점검 전용. 실제 실행에서는 입력하지 않습니다.");
            Say("  --help                         이 정보를 표시합니다.");
            Say("종료 코드: 0 성공, 2 사용법, 3 서버 준비 중, 4 코드 거부, 5 권한 거부, 6 설치 실행 실패,");
            Say("           7 연결 정보 없음, 8 설치 프로그램 내려받기 실패, 9 알 수 없는 오류");
        }

        // ---- the service check, without another dependency ---------------

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr OpenSCManager(string machine, string database, uint access);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr OpenService(IntPtr manager, string name, uint access);

        [DllImport("advapi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        static extern bool CloseServiceHandle(IntPtr handle);

        const uint ScManagerConnect = 0x0001;
        const uint ServiceQueryStatus = 0x0004;

        static bool ServiceExists(string name)
        {
            // Opening the service by name answers "is this service registered" and
            // changes nothing. Query configuration rights are not asked for, so an
            // ordinary sign-in can read it and no prompt appears.
            IntPtr manager = OpenSCManager(null, null, ScManagerConnect);
            if (manager == IntPtr.Zero)
            {
                return false;
            }
            try
            {
                IntPtr service = OpenService(manager, name, ServiceQueryStatus);
                if (service == IntPtr.Zero)
                {
                    return false;
                }
                CloseServiceHandle(service);
                return true;
            }
            finally
            {
                CloseServiceHandle(manager);
            }
        }
    }

    internal sealed class Options
    {
        public bool Check;
        public bool DryRun;
        public bool Help;
        public bool Paused = true;
        public string Origin = "";
        public string Code = "";

        public static string Parse(string[] arguments, out Options options)
        {
            options = new Options();
            for (int index = 0; index < arguments.Length; index++)
            {
                string argument = arguments[index];
                if (argument == "--check")
                {
                    options.Check = true;
                    options.Paused = false;
                }
                else if (argument == "--dry-run")
                {
                    options.DryRun = true;
                    options.Paused = false;
                }
                else if (argument == "--help")
                {
                    options.Help = true;
                    options.Paused = false;
                }
                else if (argument == "--no-pause")
                {
                    options.Paused = false;
                }
                else if (argument == "--origin" || argument == "--code")
                {
                    if (index + 1 >= arguments.Length)
                    {
                        return argument + " 값이 필요합니다.";
                    }
                    index += 1;
                    if (argument == "--origin")
                    {
                        options.Origin = arguments[index];
                    }
                    else
                    {
                        options.Code = arguments[index];
                    }
                }
                else
                {
                    return "알 수 없는 옵션: " + argument;
                }
            }
            if (options.Check && options.DryRun)
            {
                return "--check 과 --dry-run 은 함께 쓸 수 없습니다.";
            }
            return null;
        }
    }
}
