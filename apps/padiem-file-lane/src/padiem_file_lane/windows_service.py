"""Optional native Windows service wrapper. Importing never installs a service.

Operator-only commands after approval:
  python -m padiem_file_lane.windows_service --startup auto install
  python -m padiem_file_lane.windows_service start|stop|remove
Machine environment supplies the same FILE_LANE_* settings as the CLI.
"""
import os

if os.name == "nt":
    import win32service
    import win32serviceutil

    class FileLaneService(win32serviceutil.ServiceFramework):
        _svc_name_ = "PadiemFileLane"
        _svc_display_name_ = "PADIEM COM2 File Lane"
        _svc_description_ = "Disk-backed signed file upload and text parsing behind Cloudflare Tunnel"

        def __init__(self, args):
            super().__init__(args)
            self.server = None
            self.stopping = False

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.stopping = True
            if self.server is not None:
                self.server.should_exit = True

        def SvcDoRun(self):
            from .__main__ import server
            self.server = server()
            if not self.stopping:
                self.server.run()


def main():
    if os.name != "nt":
        raise SystemExit("Windows service commands require Windows")
    # -m identifies this module as __main__; pywin32 must persist the importable
    # module path rather than the temporary command entry's __main__ name.
    win32serviceutil.HandleCommandLine(FileLaneService,
        serviceClassString="padiem_file_lane.windows_service.FileLaneService")


if __name__ == "__main__":
    main()
