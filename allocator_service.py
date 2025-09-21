"""
Windows Service wrapper for Allocator AI
Install: python allocator_service.py install
Start: python allocator_service.py start
Stop: python allocator_service.py stop
Remove: python allocator_service.py remove
"""

import sys
import os
import servicemanager
import win32serviceutil
import win32service
import win32event
import subprocess

class AllocatorService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AllocatorAI"
    _svc_display_name_ = "Allocator AI Trading Bot"
    _svc_description_ = "Whale Following Trading Bot for Cryptocurrency"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.process:
            self.process.terminate()
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, '')
        )
        
        # Change to the directory containing main.py
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        # Start the main script
        try:
            self.process = subprocess.Popen([
                sys.executable, 'main.py', '--mode', 'LIVE'
            ])
            
            # Wait for service stop or process termination
            while True:
                wait_result = win32event.WaitForSingleObject(self.hWaitStop, 1000)
                if wait_result == win32event.WAIT_OBJECT_0:
                    break
                if self.process.poll() is not None:
                    # Process terminated, restart it
                    servicemanager.LogMsg(
                        servicemanager.EVENTLOG_WARNING_TYPE,
                        servicemanager.PYS_SERVICE_STARTED,
                        (self._svc_name_, 'Process terminated, restarting...')
                    )
                    self.process = subprocess.Popen([
                        sys.executable, 'main.py', '--mode', 'LIVE'
                    ])
                    
        except Exception as e:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_ERROR_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, f'Error: {str(e)}')
            )

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(AllocatorService)
