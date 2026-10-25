# The manager's descendants must leave Codex's packaged application identity.
if (-not ('YuexuDesktopProcess' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static class YuexuDesktopProcess {
    [StructLayout(LayoutKind.Sequential)] struct SecurityAttributes {
        public int length; public IntPtr descriptor; [MarshalAs(UnmanagedType.Bool)] public bool inherit;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct StartupInfo {
        public int cb; public string reserved, desktop, title;
        public uint x, y, width, height, charsX, charsY, fill, flags;
        public ushort show, reservedBytes; public IntPtr reservedData, input, output, error;
    }
    [StructLayout(LayoutKind.Sequential)] struct StartupInfoEx { public StartupInfo startup; public IntPtr attributes; }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr process, thread; public uint pid, tid; }
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern IntPtr CreateFileW(string name, uint access, uint sharing, ref SecurityAttributes security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern bool CreateProcessW(string application, StringBuilder command, IntPtr processSecurity, IntPtr threadSecurity, bool inherit, uint flags, IntPtr environment, string cwd, ref StartupInfoEx startup, out ProcessInfo process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint exitCode);

    static IntPtr Open(string file, uint access, uint disposition) {
        var security = new SecurityAttributes { length=Marshal.SizeOf(typeof(SecurityAttributes)), inherit=true };
        IntPtr result = CreateFileW(file, access, 3, ref security, disposition, 0x80, IntPtr.Zero);
        if (result == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot open launcher standard stream");
        return result;
    }
    public static Process Start(string file, string arguments, string cwd, string output, string error) {
        file=Path.GetFullPath(file); cwd=Path.GetFullPath(cwd); output=Path.GetFullPath(output); error=Path.GetFullPath(error);
        if (!File.Exists(file) || !Directory.Exists(cwd)) throw new ArgumentException("Launcher executable or working directory is missing");
        if (String.Equals(output,error,StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Launcher output and error files must differ");
        IntPtr input=IntPtr.Zero, stdout=IntPtr.Zero, stderr=IntPtr.Zero, list=IntPtr.Zero, policy=IntPtr.Zero, handles=IntPtr.Zero;
        bool initialized=false, resumed=false; ProcessInfo process=new ProcessInfo(); Process result=null;
        try {
            input=Open("NUL",0x80000000,3); stdout=Open(output,0x40000000,2); stderr=Open(error,0x40000000,2);
            IntPtr size=IntPtr.Zero;
            if (InitializeProcThreadAttributeList(IntPtr.Zero,2,0,ref size) || Marshal.GetLastWin32Error()!=122 || size==IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(),"Cannot size process attributes");
            list=Marshal.AllocHGlobal(size);
            if (!InitializeProcThreadAttributeList(list,2,0,ref size)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Cannot initialize process attributes");
            initialized=true; policy=Marshal.AllocHGlobal(4); Marshal.WriteInt32(policy,1);
            if (!UpdateProcThreadAttribute(list,0,new IntPtr(0x20012),policy,new IntPtr(4),IntPtr.Zero,IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Desktop app breakaway policy was rejected");
            handles=Marshal.AllocHGlobal(3*IntPtr.Size); Marshal.WriteIntPtr(handles,0,input); Marshal.WriteIntPtr(handles,IntPtr.Size,stdout); Marshal.WriteIntPtr(handles,2*IntPtr.Size,stderr);
            if (!UpdateProcThreadAttribute(list,0,new IntPtr(0x20002),handles,new IntPtr(3*IntPtr.Size),IntPtr.Zero,IntPtr.Zero)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Standard handle inheritance list was rejected");
            var info=new StartupInfoEx(); info.startup.cb=Marshal.SizeOf(typeof(StartupInfoEx)); info.startup.flags=0x101; info.startup.show=0;
            info.startup.input=input; info.startup.output=stdout; info.startup.error=stderr; info.attributes=list;
            var command=new StringBuilder("\""+file+"\""+(String.IsNullOrEmpty(arguments)?"":" "+arguments));
            if (!CreateProcessW(file,command,IntPtr.Zero,IntPtr.Zero,true,0x08080004,IntPtr.Zero,cwd,ref info,out process)) throw new Win32Exception(Marshal.GetLastWin32Error(),"Desktop process creation failed");
            result=Process.GetProcessById((int)process.pid);
            // Retain a managed handle before resume so exit status survives process teardown.
            IntPtr retainedHandle=result.Handle;
            if (ResumeThread(process.thread)==UInt32.MaxValue) throw new Win32Exception(Marshal.GetLastWin32Error(),"Cannot resume desktop process");
            resumed=true; return result;
        } finally {
            if (process.process!=IntPtr.Zero) { if(!resumed) TerminateProcess(process.process,1); CloseHandle(process.process); }
            if (process.thread!=IntPtr.Zero) CloseHandle(process.thread);
            if (!resumed && result!=null) result.Dispose();
            if (initialized) DeleteProcThreadAttributeList(list);
            if (list!=IntPtr.Zero) Marshal.FreeHGlobal(list);
            if (policy!=IntPtr.Zero) Marshal.FreeHGlobal(policy);
            if (handles!=IntPtr.Zero) Marshal.FreeHGlobal(handles);
            foreach(var handle in new[]{input,stdout,stderr}) if(handle!=IntPtr.Zero) CloseHandle(handle);
        }
    }
}
'@
}

function Start-DesktopProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][AllowEmptyString()][string]$ArgumentList,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$RedirectStandardOutput,
        [Parameter(Mandatory)][string]$RedirectStandardError
    )
    [YuexuDesktopProcess]::Start($FilePath, $ArgumentList, $WorkingDirectory, $RedirectStandardOutput, $RedirectStandardError)
}
