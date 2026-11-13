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
using System.Management;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
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
        const string KeyHelperUrl = "PADIEMHELPERURL";
        const string KeyHelperSha256 = "PADIEMHELPERSHA";
        // Both the agent link and the optional helper link can be long; the
        // window has to cover the whole trailer those two lines produce.
        const int TrailerWindowBytes = 8192;

        const string HandoffPath = "/api/pc/pairings/handoff";
        const string AgentServiceName = "Mesh Agent";
        const string AgentServiceKey =
            "SYSTEM\\CurrentControlSet\\Services\\Mesh Agent";
        const string AgentFileName = "MeshAgent.exe";
        const string DurableFolder = "PADIEM";
        const string InstalledExeName = "PadiemPcConnect.exe";
        const string UserHelperTaskName = "PadiemUserSessionHelper";
        const string UserHelperTaskFolder = "\\Padiem\\";
        const string UserHelperFileName = "padiem-user-helper.exe";
        const string UserHelperSecretName = "helper.secret";
        const string UserHelperStatusName = "helper-status.json";
        const string UninstallSubKey =
            "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\PADIEM-PC-Connect";
        const string UninstallDisplayName = "Padiem PC 연결";
        const string UninstallPublisher = "Padiem";
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
            new Regex("^[A-Za-z0-9._\\-]{1,128}$", RegexOptions.CultureInvariant);
        static readonly Regex Sha256HexPattern =
            new Regex("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);
        static readonly Regex ConsoleUserNamePattern =
            new Regex("^[^\\\\/\\s]+\\\\[^\\\\/\\s]+$", RegexOptions.CultureInvariant);

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
                    Say(options.Uninstall
                        ? "제거를 계속하려면 관리자 권한 승인 창에서 [예]를 눌러 주세요."
                        : "관리자 권한 승인 창이 나타나면 [예]를 눌러 주세요. 설치 프로그램은 관리자 권한으로만 동작합니다.");
                    return RelaunchElevated(arguments);
                }
                if (options.Uninstall)
                {
                    return Uninstall();
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
            string name = AgentName(tag, FixedDriveLetters(), FullMachineName());
            string durable = DurableAgentPath();
            string installerArguments = "-install --agentName=\"" + name + "\"";
            if (options.DryRun)
            {
                Say("점검 실행: 설치 프로그램은 실행하지 않았습니다.");
                Say("설치 대상 " + agentUrl);
                Say("설치 위치 " + durable);
                Say("실행 명령 " + AgentFileName + " " + installerArguments);
                Say("에이전트 이름 " + name);
                Say("사용자 세션 도우미 " + UserHelperPath() + " "
                    + (string.IsNullOrEmpty(CleanHttps(Value(KeyHelperUrl)))
                        || !IsSha256((Value(KeyHelperSha256) ?? "").Trim().ToLowerInvariant())
                        ? "(설정 없음)" : "(내려받아 SHA-256 검증)"));
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
            bool helperConfigured = !string.IsNullOrEmpty(CleanHttps(Value(KeyHelperUrl)))
                && IsSha256((Value(KeyHelperSha256) ?? "").Trim().ToLowerInvariant());
            if (helperConfigured)
            {
                // The helper is optional: its own failure is recorded locally and
                // never turns the connection that just came up into a failure.
                if (InstallUserHelper(tag))
                {
                    Say("사용자 세션 도우미를 설치했습니다.");
                }
                else
                {
                    Say("사용자 세션 도우미는 설치하지 못했습니다. PC 연결은 계속 진행됩니다.");
                }
            }
            if (!RegisterUninstaller())
            {
                Say("Windows 앱 목록에 제거 항목을 등록하지 못했습니다. 설치를 다시 실행해 주세요.");
                return ExitInstallerFailed;
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

        static string UserHelperStateDirectory()
        {
            // ProgramData, not Program Files: the secret and status live beside
            // the helper, and the task runs as the ordinary console user.
            return Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.CommonApplicationData), "Padiem");
        }

        static string UserHelperPath()
        {
            return Path.Combine(UserHelperStateDirectory(), UserHelperFileName);
        }

        static string UserHelperSecretPath()
        {
            return Path.Combine(UserHelperStateDirectory(), UserHelperSecretName);
        }

        static string UserHelperStatusPath()
        {
            return Path.Combine(UserHelperStateDirectory(), UserHelperStatusName);
        }

        static string ConsoleUserName()
        {
            // The account signed in at the console, not the elevated
            // administrator token this process runs under. Registering the
            // installer's own identity would put the helper in the wrong
            // session, which is the one thing the logon task must not do.
            try
            {
                using (ManagementObject computer = new ManagementObject(
                    "Win32_ComputerSystem.Name='.'"))
                {
                    computer.Get();
                    object value = computer["UserName"];
                    string name = value == null
                        ? null : Convert.ToString(value, CultureInfo.InvariantCulture);
                    if (!string.IsNullOrEmpty(name) && ConsoleUserNamePattern.IsMatch(name))
                    {
                        return name;
                    }
                }
            }
            catch (Exception) { }
            return null;
        }

        static bool IsSha256(string value)
        {
            return !string.IsNullOrEmpty(value) && Sha256HexPattern.IsMatch(value);
        }

        static string Sha256Hex(string path)
        {
            using (SHA256 sha = SHA256.Create())
            using (FileStream stream = File.OpenRead(path))
            {
                return BitConverter.ToString(sha.ComputeHash(stream))
                    .Replace("-", "").ToLowerInvariant();
            }
        }

        // ---- #7564: who may touch the helper's folder ---------------------
        //
        // %ProgramData% lets every local account create files inside a child
        // folder, so nothing is left to inheritance: the folder, the program,
        // the secret and the status each carry their own security descriptor.
        // SYSTEM and the Administrators group have full control, the console
        // user who runs the helper may read (and run), and no other account is
        // named. Accounts are SIDs, never display names a localized Windows
        // spells differently.
        //
        // The accounts travel as a parameter so the same code can be walked
        // against a real folder by an account that is not an administrator. The
        // install itself only ever passes ShippedHelperAccounts().
        internal const string SystemSid = "S-1-5-18";
        internal const string AdministratorsSid = "S-1-5-32-544";
        static readonly Regex SidPattern =
            new Regex("^S-1-[0-9]+(-[0-9]+)+$", RegexOptions.CultureInvariant);

        internal sealed class HelperAccounts
        {
            // Who owns what the install creates, which group has full control
            // beside SYSTEM, and whose existing folder the install will adopt.
            public readonly string Owner;
            public readonly string Administrators;
            public readonly string[] TrustedOwners;

            public HelperAccounts(string owner, string administrators, string[] trustedOwners)
            {
                Owner = owner;
                Administrators = administrators;
                TrustedOwners = trustedOwners;
            }
        }

        internal static HelperAccounts ShippedHelperAccounts()
        {
            // Whose folder this install will work in: SYSTEM, the Administrators
            // group, and the administrator account running this very install -
            // with account control off, Windows records that account, not the
            // group, as the owner of what an administrator creates. A folder any
            // other account made first is never adopted.
            List<string> trusted = new List<string>();
            trusted.Add(SystemSid);
            trusted.Add(AdministratorsSid);
            try
            {
                using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                {
                    if (identity.User != null
                        && new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))
                    {
                        trusted.Add(identity.User.Value);
                    }
                }
            }
            catch (Exception) { }
            return new HelperAccounts(AdministratorsSid, AdministratorsSid, trusted.ToArray());
        }

        internal static string AccountSid(string account)
        {
            // The SID Windows resolves the account to. A name that does not
            // resolve is not an account this install may grant anything to.
            try
            {
                string sid = ((SecurityIdentifier)new NTAccount(account)
                    .Translate(typeof(SecurityIdentifier))).Value;
                return SidPattern.IsMatch(sid) ? sid : null;
            }
            catch (Exception)
            {
                return null;
            }
        }

        internal static string HelperSddl(string kind, string userSid, HelperAccounts accounts)
        {
            // One descriptor per kind of object. "P" cuts inheritance. The
            // folder's entries carry OICI, so a file created inside starts from
            // the same three accounts. 0x1200a9 is read and execute (folder,
            // program); 0x120089 is read (secret, status). Without a user only
            // SYSTEM and Administrators stay.
            if (!SidPattern.IsMatch(accounts.Owner ?? "")
                || !SidPattern.IsMatch(accounts.Administrators ?? ""))
            {
                throw new ArgumentException("padiem_helper_owner_sid");
            }
            if (!string.IsNullOrEmpty(userSid) && !SidPattern.IsMatch(userSid))
            {
                throw new ArgumentException("padiem_helper_user_sid");
            }
            string inherit = kind == "folder" ? "OICI" : "";
            string rights = kind == "data" ? "0x120089" : "0x1200a9";
            string sddl = "O:" + accounts.Owner + "D:PAI(A;" + inherit + ";FA;;;" + SystemSid
                + ")(A;" + inherit + ";FA;;;" + accounts.Administrators + ")";
            if (!string.IsNullOrEmpty(userSid))
            {
                sddl += "(A;" + inherit + ";" + rights + ";;;" + userSid + ")";
            }
            return sddl;
        }

        internal static FileSystemSecurity HelperSecurity(string kind, string userSid,
            HelperAccounts accounts)
        {
            // Only the owner and the access list are set, so applying the
            // descriptor never asks for the audit privilege.
            FileSystemSecurity security = kind == "folder"
                ? (FileSystemSecurity)new DirectorySecurity() : new FileSecurity();
            security.SetSecurityDescriptorSddlForm(HelperSddl(kind, userSid, accounts),
                AccessControlSections.Owner | AccessControlSections.Access);
            return security;
        }

        internal static string SecurityFacts(FileSystemSecurity security)
        {
            // Owner, whether inheritance is cut, and every entry: what it takes
            // to say two descriptors grant the same things to the same accounts.
            List<string> rules = new List<string>();
            foreach (FileSystemAccessRule rule in security.GetAccessRules(
                true, true, typeof(SecurityIdentifier)))
            {
                rules.Add(rule.IdentityReference.Value
                    + "/" + ((int)rule.AccessControlType).ToString(CultureInfo.InvariantCulture)
                    + "/" + ((int)rule.FileSystemRights).ToString(CultureInfo.InvariantCulture)
                    + "/" + ((int)rule.InheritanceFlags).ToString(CultureInfo.InvariantCulture)
                    + "/" + ((int)rule.PropagationFlags).ToString(CultureInfo.InvariantCulture)
                    + "/" + (rule.IsInherited ? "1" : "0"));
            }
            rules.Sort(StringComparer.Ordinal);
            IdentityReference owner = security.GetOwner(typeof(SecurityIdentifier));
            return (owner == null ? "" : owner.Value)
                + ";" + (security.AreAccessRulesProtected ? "1" : "0")
                + ";" + string.Join(",", rules.ToArray());
        }

        internal static bool HelperSecurityMatches(string path, string kind, string userSid,
            HelperAccounts accounts)
        {
            // Reads back what the disk holds. That the call which set a
            // descriptor did not fail is not the fact; the descriptor that is
            // there now is. A link is never the object this install made.
            try
            {
                FileAttributes attributes = File.GetAttributes(path);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                {
                    return false;
                }
                bool folder = (attributes & FileAttributes.Directory) != 0;
                if (folder != (kind == "folder"))
                {
                    return false;
                }
                FileSystemSecurity actual = folder
                    ? (FileSystemSecurity)Directory.GetAccessControl(path)
                    : File.GetAccessControl(path);
                return SecurityFacts(actual) == SecurityFacts(HelperSecurity(kind, userSid, accounts));
            }
            catch (Exception)
            {
                return false;
            }
        }

        internal static string FolderAdoptionRefusal(string path, HelperAccounts accounts)
        {
            // "" when the folder that is already there may be worked in,
            // otherwise why not. It is adopted only from an owner this install
            // trusts, and never when it is a link that leads somewhere else.
            FileAttributes attributes = File.GetAttributes(path);
            if ((attributes & FileAttributes.Directory) == 0)
            {
                return "state_dir_not_a_folder";
            }
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                return "state_dir_is_a_link";
            }
            string owner = null;
            try
            {
                IdentityReference found = Directory.GetAccessControl(path)
                    .GetOwner(typeof(SecurityIdentifier));
                owner = found == null ? null : found.Value;
            }
            catch (Exception)
            {
                owner = null;
            }
            if (string.IsNullOrEmpty(owner) || Array.IndexOf(accounts.TrustedOwners, owner) < 0)
            {
                return "state_dir_owner_untrusted";
            }
            return "";
        }

        internal static string ProtectHelperDirectory(string path, string userSid,
            HelperAccounts accounts)
        {
            // "" when the folder is this install's own and locked, otherwise the
            // reason it will not be used. A folder that is not there is created
            // already carrying its descriptor - there is no moment it exists
            // with the inherited one. A folder that is there is checked before
            // it is touched, and what the disk holds afterwards is read back
            // either way.
            DirectorySecurity security = (DirectorySecurity)HelperSecurity("folder", userSid, accounts);
            if (Directory.Exists(path) || File.Exists(path))
            {
                string refusal = FolderAdoptionRefusal(path, accounts);
                if (refusal.Length > 0)
                {
                    return refusal;
                }
                try { Directory.SetAccessControl(path, security); }
                catch (Exception) { return "state_dir_acl_failed"; }
            }
            else
            {
                try { Directory.CreateDirectory(path, security); }
                catch (Exception) { return "state_dir_create_failed"; }
            }
            return HelperSecurityMatches(path, "folder", userSid, accounts)
                ? "" : "state_dir_acl_unverified";
        }

        internal static FileStream CreateLockedFile(string path, string kind, string userSid,
            HelperAccounts accounts)
        {
            // A write stream on a file that is created already carrying its
            // descriptor. CreateNew refuses a name that exists, so a file
            // somebody left there is never written through.
            return new FileStream(path, FileMode.CreateNew, FileSystemRights.Write,
                FileShare.None, 4096, FileOptions.None,
                (FileSecurity)HelperSecurity(kind, userSid, accounts));
        }

        internal static void MoveIntoPlace(string source, string target)
        {
            // A rename inside the locked folder keeps the descriptor the new
            // file was created with. The old file is removed first, not
            // replaced in place: replacing would hand the new bytes to whatever
            // owner and entries the old file had.
            if (File.Exists(target))
            {
                File.SetAttributes(target, FileAttributes.Normal);
                File.Delete(target);
            }
            File.Move(source, target);
        }

        internal static void WriteLockedFile(string path, string kind, byte[] payload,
            string userSid, HelperAccounts accounts)
        {
            // The bytes go into a new file under a name nothing reads yet, and
            // the file gets its name only once it is complete.
            string pending = path + "." + Guid.NewGuid().ToString("N") + ".new";
            try
            {
                using (FileStream stream = CreateLockedFile(pending, kind, userSid, accounts))
                {
                    stream.Write(payload, 0, payload.Length);
                }
                MoveIntoPlace(pending, path);
            }
            finally
            {
                try { if (File.Exists(pending)) { File.Delete(pending); } }
                catch (Exception) { }
            }
        }

        internal static bool PlaceHelperProgram(string source, string target, string sha256,
            string userSid, HelperAccounts accounts)
        {
            // The program is copied into a new file that already carries its
            // descriptor, hashed where it now lies, and only then given its
            // name. True when the bytes that were placed are the reviewed ones.
            string pending = target + "." + Guid.NewGuid().ToString("N") + ".new";
            try
            {
                using (FileStream writer = CreateLockedFile(pending, "program", userSid, accounts))
                using (FileStream reader = File.OpenRead(source))
                {
                    reader.CopyTo(writer);
                }
                if (!string.Equals(Sha256Hex(pending), sha256, StringComparison.Ordinal))
                {
                    return false;
                }
                MoveIntoPlace(pending, target);
                return true;
            }
            finally
            {
                try { if (File.Exists(pending)) { File.Delete(pending); } }
                catch (Exception) { }
            }
        }

        internal static void WriteHelperSecret(string path, string userSid, HelperAccounts accounts)
        {
            // 32 random bytes as 64 lowercase hex characters - the shape the
            // Connector's own provisioning lane writes. Every install makes a new
            // one: a file that is already there is never read back or kept,
            // because whoever wrote it knows what is in it. The value never goes
            // to the console or to helper-status.json.
            byte[] bytes = new byte[32];
            using (RandomNumberGenerator random = RandomNumberGenerator.Create())
            {
                random.GetBytes(bytes);
            }
            StringBuilder hex = new StringBuilder(bytes.Length * 2);
            for (int index = 0; index < bytes.Length; index++)
            {
                hex.Append(bytes[index].ToString("x2", CultureInfo.InvariantCulture));
            }
            WriteLockedFile(path, "data", new UTF8Encoding(false).GetBytes(hex.ToString() + "\n"),
                userSid, accounts);
        }

        internal static bool StopUserHelper(string helperExe, string taskPath)
        {
            // A helper that is still running keeps the old secret in memory and
            // its program file open, so a re-install ends it first: the task
            // instance, then any process still running this exact file. True
            // when none is left.
            if (!string.IsNullOrEmpty(taskPath))
            {
                RunSchtasks("/End /TN \"" + taskPath + "\"");
            }
            string name = Path.GetFileNameWithoutExtension(helperExe);
            for (int attempt = 0; attempt < 20; attempt++)
            {
                int running = 0;
                foreach (Process process in Process.GetProcessesByName(name))
                {
                    using (process)
                    {
                        string image = null;
                        try { image = process.MainModule.FileName; }
                        catch (Exception) { image = null; }
                        if (image == null
                            || !image.Equals(helperExe, StringComparison.OrdinalIgnoreCase))
                        {
                            continue;
                        }
                        running++;
                        try { process.Kill(); }
                        catch (Exception) { }
                    }
                }
                if (running == 0)
                {
                    return true;
                }
                Thread.Sleep(250);
            }
            return false;
        }

        internal static bool QuarantineForeignContent(string stateDir, HelperAccounts accounts,
            out string quarantine, out int moved)
        {
            // Once the folder is locked, only plain files owned by SYSTEM or an
            // administrator stay in it. Anything else - a file another account
            // put there while the folder was open to it, a subfolder, a link -
            // is moved, by one rename each and never by a walk through its
            // contents, into a sibling folder only SYSTEM and administrators can
            // open. True when nothing of the kind is left.
            quarantine = null;
            moved = 0;
            List<string> foreign = new List<string>();
            foreach (string child in Directory.GetFileSystemEntries(stateDir))
            {
                FileAttributes attributes = File.GetAttributes(child);
                string owner = null;
                if ((attributes & (FileAttributes.Directory | FileAttributes.ReparsePoint)) == 0)
                {
                    try
                    {
                        IdentityReference found = File.GetAccessControl(child)
                            .GetOwner(typeof(SecurityIdentifier));
                        owner = found == null ? null : found.Value;
                    }
                    catch (Exception)
                    {
                        owner = null;
                    }
                }
                if (string.IsNullOrEmpty(owner) || Array.IndexOf(accounts.TrustedOwners, owner) < 0)
                {
                    foreign.Add(child);
                }
            }
            if (foreign.Count == 0)
            {
                return true;
            }
            quarantine = stateDir.TrimEnd('\\') + ".quarantine-"
                + DateTime.UtcNow.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture)
                + "-" + Guid.NewGuid().ToString("N").Substring(0, 8);
            Directory.CreateDirectory(quarantine,
                (DirectorySecurity)HelperSecurity("folder", null, accounts));
            if (!HelperSecurityMatches(quarantine, "folder", null, accounts))
            {
                return false;
            }
            foreach (string child in foreign)
            {
                try
                {
                    string destination = Path.Combine(quarantine, Path.GetFileName(child));
                    if ((File.GetAttributes(child) & FileAttributes.Directory) != 0)
                    {
                        Directory.Move(child, destination);
                    }
                    else
                    {
                        File.Move(child, destination);
                    }
                    moved++;
                }
                catch (Exception) { }
            }
            return moved == foreign.Count;
        }

        internal static string HelperInstallFault(string directory, string userSid,
            HelperAccounts accounts)
        {
            // Reads the finished install back before the helper is allowed to
            // start from it. "" when the folder, the program and the secret
            // each carry exactly their own descriptor.
            if (!HelperSecurityMatches(directory, "folder", userSid, accounts))
            {
                return "state_dir_acl_unverified";
            }
            if (!HelperSecurityMatches(Path.Combine(directory, UserHelperFileName),
                    "program", userSid, accounts))
            {
                return "program_acl_unverified";
            }
            if (!HelperSecurityMatches(Path.Combine(directory, UserHelperSecretName),
                    "data", userSid, accounts))
            {
                return "secret_acl_failed";
            }
            return "";
        }

        internal static string InstallHelperFiles(string directory, string sourceExe,
            string sha256, string userSid, HelperAccounts accounts, string taskPath)
        {
            // What happens between "the downloaded bytes are the reviewed ones"
            // and "register the task": end a running helper, clear what does
            // not belong, place the program, write a new secret, read it all
            // back. "" when the folder is ready to be served from.
            string program = Path.Combine(directory, UserHelperFileName);
            string secret = Path.Combine(directory, UserHelperSecretName);
            bool stopped = false;
            bool verified = false;
            try
            {
                if (!StopUserHelper(program, taskPath))
                {
                    return "helper_still_running";
                }
                stopped = true;
                string quarantine;
                int moved;
                bool cleared = QuarantineForeignContent(directory, accounts, out quarantine, out moved);
                if (quarantine != null)
                {
                    Say("도우미 설치 폴더에 있던, 관리자나 SYSTEM 소유가 아닌 항목 "
                        + moved.ToString(CultureInfo.InvariantCulture) + "개를 "
                        + quarantine + " 폴더로 옮겼습니다.");
                }
                if (!cleared)
                {
                    return "state_dir_foreign_content";
                }
                if (!PlaceHelperProgram(sourceExe, program, sha256, userSid, accounts))
                {
                    return "sha256_mismatch";
                }
                WriteHelperSecret(secret, userSid, accounts);
                string fault = HelperInstallFault(directory, userSid, accounts);
                if (fault.Length > 0)
                {
                    return fault;
                }
                verified = true;
                return "";
            }
            finally
            {
                if (stopped && !verified)
                {
                    // The old helper was ended and the new install did not pass
                    // its read-back. Without a secret the helper refuses to
                    // start, so a folder that was not verified is never served
                    // from.
                    try { File.Delete(secret); }
                    catch (Exception) { }
                }
            }
        }

        static string XmlEscape(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "";
            }
            return value.Replace("&", "&amp;").Replace("<", "&lt;")
                .Replace(">", "&gt;").Replace("\"", "&quot;")
                .Replace("'", "&apos;");
        }

        static string JsonEscape(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "";
            }
            StringBuilder escaped = new StringBuilder(value.Length);
            for (int index = 0; index < value.Length; index++)
            {
                char character = value[index];
                if (character == '"' || character == '\\')
                {
                    escaped.Append('\\').Append(character);
                }
                else if (character < ' ')
                {
                    escaped.Append(' ');
                }
                else
                {
                    escaped.Append(character);
                }
            }
            return escaped.ToString();
        }

        static void WriteUserHelperStatus(string status, string reason,
            string deviceId, string sha256, string user, string userSid)
        {
            // Local evidence only; the secret is never a member of this object.
            // The status is written only into a folder this install would
            // adopt, as a new file that already carries its descriptor and is
            // then renamed into place - never through a file that was already
            // lying there.
            try
            {
                string directory = UserHelperStateDirectory();
                HelperAccounts accounts = ShippedHelperAccounts();
                if (!Directory.Exists(directory)
                    || FolderAdoptionRefusal(directory, accounts).Length > 0)
                {
                    return;
                }
                StringBuilder json = new StringBuilder();
                json.Append("{\"status\":\"").Append(JsonEscape(status)).Append("\"");
                json.Append(",\"task\":\"").Append(JsonEscape(UserHelperTaskName)).Append("\"");
                if (!string.IsNullOrEmpty(deviceId))
                {
                    json.Append(",\"device_id\":\"").Append(JsonEscape(deviceId)).Append("\"");
                }
                if (!string.IsNullOrEmpty(sha256))
                {
                    json.Append(",\"sha256\":\"").Append(JsonEscape(sha256)).Append("\"");
                }
                if (!string.IsNullOrEmpty(user))
                {
                    json.Append(",\"user\":\"").Append(JsonEscape(user)).Append("\"");
                }
                if (!string.IsNullOrEmpty(reason))
                {
                    json.Append(",\"reason\":\"").Append(JsonEscape(reason)).Append("\"");
                }
                json.Append("}\n");
                WriteLockedFile(UserHelperStatusPath(), "data",
                    new UTF8Encoding(false).GetBytes(json.ToString()), userSid, accounts);
            }
            catch (Exception) { }
        }

        static void SayHelperStopped(string reason)
        {
            // An install that stops says why. The reason is a fixed code; no
            // pairing value is ever part of it.
            if (reason == "state_dir_owner_untrusted")
            {
                Say("도우미 설치 폴더 " + UserHelperStateDirectory()
                    + " 의 소유자가 관리자나 SYSTEM이 아니어서, 그 폴더를 쓰지 않고 도우미 설치를 멈췄습니다."
                    + " 관리자가 폴더를 확인해 지운 뒤 다시 설치해 주세요.");
            }
            Say("사용자 세션 도우미 설치를 멈춘 이유: " + reason);
        }

        static string UserHelperTaskXml(string helperExe, string secretPath,
            string deviceId, string user)
        {
            string arguments = "--device-id \"" + deviceId
                + "\" --secret-file \"" + secretPath + "\"";
            return "<?xml version=\"1.0\" encoding=\"UTF-16\"?>\r\n"
                + "<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\">\r\n"
                + "  <RegistrationInfo><Description>PADIEM user-session helper (#7108). One request per process.</Description></RegistrationInfo>\r\n"
                + "  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>"
                + XmlEscape(user) + "</UserId></LogonTrigger></Triggers>\r\n"
                + "  <Principals><Principal id=\"Author\"><UserId>" + XmlEscape(user)
                + "</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>\r\n"
                + "  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
                + "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
                + "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
                + "<StartWhenAvailable>true</StartWhenAvailable>"
                + "<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled>"
                + "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings>\r\n"
                + "  <Actions Context=\"Author\"><Exec><Command>" + XmlEscape(helperExe)
                + "</Command><Arguments>" + XmlEscape(arguments)
                + "</Arguments><WorkingDirectory>"
                + XmlEscape(Path.GetDirectoryName(helperExe))
                + "</WorkingDirectory></Exec></Actions>\r\n"
                + "</Task>\r\n";
        }

        static bool RunSchtasks(string arguments)
        {
            try
            {
                string schtasks = Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.System), "schtasks.exe");
                if (!File.Exists(schtasks))
                {
                    return false;
                }
                ProcessStartInfo start = new ProcessStartInfo(schtasks, arguments);
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
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

        static bool RegisterUserHelperTask(string helperExe, string secretPath,
            string deviceId, string user)
        {
            // ONLOGON + InteractiveToken + LeastPrivilege: the helper starts in
            // the console user's own session, never elevated. Creating it from
            // this already-elevated process does not ask for a second approval.
            string taskPath = UserHelperTaskFolder + UserHelperTaskName;
            string temp = Path.Combine(Path.GetTempPath(),
                "padiem-helper-task-" + Guid.NewGuid().ToString("N") + ".xml");
            try
            {
                File.WriteAllText(temp, UserHelperTaskXml(
                    helperExe, secretPath, deviceId, user), Encoding.Unicode);
                if (!RunSchtasks("/Create /TN \"" + taskPath + "\" /XML \"" + temp + "\" /F"))
                {
                    return false;
                }
                // A re-run replaces the task; starting it now puts the helper in
                // the session without waiting for the next logon.
                RunSchtasks("/Run /TN \"" + taskPath + "\"");
                return true;
            }
            catch (Exception)
            {
                return false;
            }
            finally
            {
                try { File.Delete(temp); } catch (Exception) { }
            }
        }

        static bool InstallUserHelper(string tag)
        {
            // Lock the folder, download, verify, end a running helper, clear
            // what does not belong, place, new secret, read the install back,
            // logon task, status: the same order as the PowerShell lanes. Every
            // failure is recorded, said and returns false; the agent connection
            // that already came up stands.
            string url = CleanHttps(Value(KeyHelperUrl));
            string sha = (Value(KeyHelperSha256) ?? "").Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(url) || !IsSha256(sha))
            {
                return false;
            }
            string deviceId = tag != null && InstallTag.IsMatch(tag)
                ? tag : Guid.NewGuid().ToString("N");
            string user = ConsoleUserName();
            string userSid = string.IsNullOrEmpty(user) ? null : AccountSid(user);
            string reason;
            try
            {
                if (string.IsNullOrEmpty(userSid))
                {
                    reason = string.IsNullOrEmpty(user)
                        ? "no_console_user" : "console_user_unresolved";
                }
                else
                {
                    reason = ProvisionUserHelper(url, sha, deviceId, user, userSid);
                }
            }
            catch (Exception)
            {
                reason = "provision_failed";
            }
            WriteUserHelperStatus(reason.Length == 0 ? "installed" : "not_installed",
                reason, deviceId, sha, user, userSid);
            if (reason.Length > 0)
            {
                SayHelperStopped(reason);
            }
            return reason.Length == 0;
        }

        static string ProvisionUserHelper(string url, string sha, string deviceId,
            string user, string userSid)
        {
            // "" when the helper is installed, otherwise the reason it is not.
            // Nothing is downloaded, stopped or written until the folder is
            // this install's own: a folder another account made first is
            // refused here, before anything on this PC has changed.
            HelperAccounts accounts = ShippedHelperAccounts();
            string directory = UserHelperStateDirectory();
            string refusal = ProtectHelperDirectory(directory, userSid, accounts);
            if (refusal.Length > 0)
            {
                return refusal;
            }
            string temp = Path.Combine(Path.GetTempPath(),
                "padiem-user-helper-" + Guid.NewGuid().ToString("N") + ".exe");
            try
            {
                if (Download(url, temp) <= 0)
                {
                    return "download_failed";
                }
                if (!string.Equals(Sha256Hex(temp), sha, StringComparison.Ordinal))
                {
                    return "sha256_mismatch";
                }
                string fault = InstallHelperFiles(directory, temp, sha, userSid, accounts,
                    UserHelperTaskFolder + UserHelperTaskName);
                if (fault.Length > 0)
                {
                    return fault;
                }
                if (!RegisterUserHelperTask(
                        UserHelperPath(), UserHelperSecretPath(), deviceId, user))
                {
                    return "task_registration_failed";
                }
                return "";
            }
            finally
            {
                try { File.Delete(temp); } catch (Exception) { }
            }
        }

        static string InstalledConnectExePath()
        {
            return Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.ProgramFiles), DurableFolder, InstalledExeName);
        }

        static string ProductVersion()
        {
            try
            {
                return typeof(PadiemPcConnect).Assembly.GetName().Version.ToString();
            }
            catch (Exception)
            {
                return "1.0.0.0";
            }
        }

        static bool RegisterUninstaller()
        {
            // The Windows app list needs an uninstaller that stays on this PC. The
            // downloaded file is not a stable location, so keep one copy of this
            // exact program beside the agent and register that copy.
            try
            {
                string source = OwnPath();
                if (source == null)
                {
                    return false;
                }
                string target = InstalledConnectExePath();
                string folder = Path.GetDirectoryName(target);
                if (!Directory.Exists(folder))
                {
                    Directory.CreateDirectory(folder);
                }
                if (!string.Equals(Path.GetFullPath(source), Path.GetFullPath(target),
                        StringComparison.OrdinalIgnoreCase))
                {
                    File.Copy(source, target, true);
                }
                using (Microsoft.Win32.RegistryKey baseKey =
                    Microsoft.Win32.RegistryKey.OpenBaseKey(
                        Microsoft.Win32.RegistryHive.LocalMachine,
                        Microsoft.Win32.RegistryView.Registry64))
                using (Microsoft.Win32.RegistryKey key = baseKey.CreateSubKey(UninstallSubKey))
                {
                    if (key == null)
                    {
                        return false;
                    }
                    key.SetValue("DisplayName", UninstallDisplayName,
                        Microsoft.Win32.RegistryValueKind.String);
                    key.SetValue("Publisher", UninstallPublisher,
                        Microsoft.Win32.RegistryValueKind.String);
                    key.SetValue("DisplayVersion", ProductVersion(),
                        Microsoft.Win32.RegistryValueKind.String);
                    key.SetValue("UninstallString",
                        "\"" + target + "\" -Uninstall",
                        Microsoft.Win32.RegistryValueKind.String);
                    key.SetValue("InstallLocation", folder,
                        Microsoft.Win32.RegistryValueKind.String);
                    key.SetValue("NoModify", 1, Microsoft.Win32.RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, Microsoft.Win32.RegistryValueKind.DWord);
                }
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        static int Uninstall()
        {
            string folder = Path.GetDirectoryName(DurableAgentPath());
            string agent = DurableAgentPath();
            if (!File.Exists(agent))
            {
                string registered = RegisteredAgentPath();
                if (registered != null)
                {
                    agent = registered;
                }
            }
            // -fulluninstall is the agent's own removal switch: it stops the
            // service, unregisters it and removes the files it placed.
            if (File.Exists(agent))
            {
                RunQuiet(agent, "-fulluninstall");
            }
            // A service that survived an interrupted removal is still not this
            // program's to leave behind. sc.exe is the OS's own fallback.
            if (ServiceExists(AgentServiceName))
            {
                string sc = Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.System), "sc.exe");
                if (File.Exists(sc))
                {
                    RunQuiet(sc, "stop \"" + AgentServiceName + "\"");
                    RunQuiet(sc, "delete \"" + AgentServiceName + "\"");
                }
            }
            DeleteUninstallRegistration();
            // This executable itself lives in the folder it must remove. Delete
            // the folder from outside the install directory after this process
            // has exited; running rmdir from inside it leaves the folder behind.
            ScheduleFolderRemoval(folder);
            Say("Padiem PC 연결을 제거했습니다. Windows 앱 목록에서도 사라집니다.");
            Say("웹의 '내 PC 연결'에서 연결 해제도 확인해 주세요.");
            return ExitOk;
        }

        static void DeleteUninstallRegistration()
        {
            try
            {
                using (Microsoft.Win32.RegistryKey baseKey =
                    Microsoft.Win32.RegistryKey.OpenBaseKey(
                        Microsoft.Win32.RegistryHive.LocalMachine,
                        Microsoft.Win32.RegistryView.Registry64))
                {
                    baseKey.DeleteSubKeyTree(UninstallSubKey, false);
                }
            }
            catch (Exception)
            {
            }
        }

        static void ScheduleFolderRemoval(string folder)
        {
            try
            {
                ProcessStartInfo start = new ProcessStartInfo("cmd.exe",
                    "/c ping 127.0.0.1 -n 3 > nul & rmdir /s /q \"" + folder + "\"");
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                Process.Start(start);
            }
            catch (Exception)
            {
            }
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
            string helperUrl = CleanHttps(Value(KeyHelperUrl));
            string helperSha = (Value(KeyHelperSha256) ?? "").Trim().ToLowerInvariant();
            Console.WriteLine("CONNECT_EXE_CHECK_HELPER_URL_PRESENT=" + (string.IsNullOrEmpty(helperUrl) ? "0" : "1"));
            Console.WriteLine("CONNECT_EXE_CHECK_HELPER_SHA_PRESENT=" + (IsSha256(helperSha) ? "1" : "0"));
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
                    AgentName(tag, FixedDriveLetters(), FullMachineName()));
            }
            return ExitOk;
        }

        // ---- the four facts the installer needs --------------------------

        static string FullMachineName()
        {
            // The whole name Windows gave this machine, not the 15-character
            // NetBIOS form Environment.MachineName returns: a computer named
            // "PADIEM-COMMAND-CENTER" reports "PADIEM-COMMAND-" through that
            // property, and the server then stores a truncated name as the
            // link's first label. Dns.GetHostName() answers with the DNS host
            // name - the same string a UNC share path names - and falls back to
            // Environment.MachineName when it cannot be read.
            try
            {
                string dns = Dns.GetHostName();
                if (!string.IsNullOrEmpty(dns))
                {
                    return dns;
                }
            }
            catch (Exception) { }
            return Environment.MachineName;
        }

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
            Say("  -Uninstall                     Windows 앱 목록에서 Padiem PC 연결을 제거합니다.");
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
        public bool Uninstall;

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
                else if (argument.Equals("-Uninstall", StringComparison.OrdinalIgnoreCase)
                      || argument.Equals("--uninstall", StringComparison.OrdinalIgnoreCase))
                {
                    options.Uninstall = true;
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
