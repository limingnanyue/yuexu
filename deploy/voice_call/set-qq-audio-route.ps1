$ErrorActionPreference = 'Stop'
if (-not ('YuexuIndependentAudio' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class YuexuIndependentAudio {
    public class Endpoint { public int Flow; public string Name, Id; }
    [StructLayout(LayoutKind.Sequential)] struct Key { public Guid id; public uint pid; }
    [StructLayout(LayoutKind.Explicit, Size=24)] struct Variant { [FieldOffset(0)] public ushort type; [FieldOffset(8)] public IntPtr text; }
    [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid cls,IntPtr outer,uint context,ref Guid iid,out IntPtr result);
    [DllImport("ole32.dll")] static extern int PropVariantClear(ref Variant value);
    [DllImport("combase.dll")] static extern int RoInitialize(uint mode);
    [DllImport("combase.dll")] static extern void RoUninitialize();
    [DllImport("combase.dll")] static extern int WindowsCreateString([MarshalAs(UnmanagedType.LPWStr)]string value,uint length,out IntPtr result);
    [DllImport("combase.dll")] static extern int WindowsDeleteString(IntPtr value);
    [DllImport("combase.dll")] static extern IntPtr WindowsGetStringRawBuffer(IntPtr value,out uint length);
    [DllImport("combase.dll")] static extern int RoGetActivationFactory(IntPtr name,ref Guid iid,out IntPtr result);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr value);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern int GetApplicationUserModelId(IntPtr process,ref uint length,StringBuilder value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetReference(IntPtr self,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetCount(IntPtr self,out uint count);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetItem(IntPtr self,uint index,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int EnumDevices(IntPtr self,int flow,uint state,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetDefault(IntPtr self,int flow,int role,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetStore(IntPtr self,uint access,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetProperty(IntPtr self,ref Key key,out Variant result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Activate(IntPtr self,ref Guid iid,uint context,IntPtr parameters,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Query(IntPtr self,ref Guid iid,out IntPtr result);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetNumber(IntPtr self,out uint value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int PolicyGet(IntPtr self,uint pid,int flow,int role,out IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int PolicySet(IntPtr self,uint pid,int flow,int role,IntPtr value);
    static T Method<T>(IntPtr value,int index) where T:class { return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(value),index*IntPtr.Size),typeof(T)) as T; }
    static void Check(int result) { Marshal.ThrowExceptionForHR(result); }
    static IntPtr Enumerator() { Guid cls=new Guid("bcde0395-e52f-467c-8e3d-c4579291692e"),iid=new Guid("a95664d2-9614-4f35-a746-de8db63617e6");IntPtr value;Check(CoCreateInstance(ref cls,IntPtr.Zero,23,ref iid,out value));return value; }
    static string Id(IntPtr value) { IntPtr text;Check(Method<GetReference>(value,5)(value,out text));try{return Marshal.PtrToStringUni(text);}finally{Marshal.FreeCoTaskMem(text);} }
    static void Release(IntPtr value) { if(value!=IntPtr.Zero)Marshal.Release(value); }
    public static int AppIdentity(uint pid) {
        IntPtr process=OpenProcess(0x1000,false,pid);if(process==IntPtr.Zero)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
        try{uint length=0;return GetApplicationUserModelId(process,ref length,null);}finally{CloseHandle(process);}
    }
    public static Endpoint[] Devices() {
        var result=new List<Endpoint>();IntPtr enumerator=Enumerator();
        try{for(int flow=0;flow<2;flow++){IntPtr list;Check(Method<EnumDevices>(enumerator,3)(enumerator,flow,1,out list));
            try{uint count;Check(Method<GetCount>(list,3)(list,out count));for(uint index=0;index<count;index++){IntPtr device;Check(Method<GetItem>(list,4)(list,index,out device));
                try{IntPtr store;Check(Method<GetStore>(device,4)(device,0,out store));try{var key=new Key{id=new Guid("a45c254e-df1c-4efd-8020-67d146a850e0"),pid=14};Variant value;Check(Method<GetProperty>(store,5)(store,ref key,out value));
                    try{if(value.type!=31)throw new InvalidOperationException("Unknown endpoint name type");result.Add(new Endpoint{Flow=flow,Name=Marshal.PtrToStringUni(value.text),Id=Id(device)});}finally{PropVariantClear(ref value);}
                }finally{Release(store);}}finally{Release(device);}
            }}finally{Release(list);}
        }}finally{Release(enumerator);}return result.ToArray();
    }
    public static string[] Defaults() {
        var result=new List<string>();IntPtr enumerator=Enumerator();
        try{for(int flow=0;flow<2;flow++)for(int role=0;role<3;role++){IntPtr device;Check(Method<GetDefault>(enumerator,4)(enumerator,flow,role,out device));try{result.Add(Id(device));}finally{Release(device);}}}finally{Release(enumerator);}return result.ToArray();
    }
    public static uint[] ActiveSessionPids() {
        var result=new HashSet<uint>();IntPtr enumerator=Enumerator(),devices=IntPtr.Zero;Check(Method<EnumDevices>(enumerator,3)(enumerator,0,1,out devices));
        try{uint count;Check(Method<GetCount>(devices,3)(devices,out count));for(uint index=0;index<count;index++){IntPtr device=IntPtr.Zero,manager=IntPtr.Zero,sessions=IntPtr.Zero;
            try{Check(Method<GetItem>(devices,4)(devices,index,out device));Guid iid=new Guid("bfa971f1-4d5e-40bb-935e-967039bfbee4");Check(Method<Activate>(device,3)(device,ref iid,23,IntPtr.Zero,out manager));Check(Method<GetReference>(manager,5)(manager,out sessions));uint sessionCount;Check(Method<GetCount>(sessions,3)(sessions,out sessionCount));
                for(uint j=0;j<sessionCount;j++){IntPtr session=IntPtr.Zero,control=IntPtr.Zero;try{Check(Method<GetItem>(sessions,4)(sessions,j,out session));Guid controlId=new Guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d");Check(Method<Query>(session,0)(session,ref controlId,out control));uint state,pid;Check(Method<GetNumber>(control,3)(control,out state));Check(Method<GetNumber>(control,14)(control,out pid));if(state==1&&pid>0)result.Add(pid);}finally{Release(control);Release(session);}}
            }finally{Release(sessions);Release(manager);Release(device);}
        }}finally{Release(devices);Release(enumerator);}var array=new uint[result.Count];result.CopyTo(array);return array;
    }
    public static string Preference(uint pid,int flow,int role,bool write,string target) {
        IntPtr name=IntPtr.Zero,factory=IntPtr.Zero,input=IntPtr.Zero,output=IntPtr.Zero;int initialized=RoInitialize(1);if(initialized<0&&initialized!=unchecked((int)0x80010106))Check(initialized);
        try{string cls="Windows.Media.Internal.AudioPolicyConfig";Check(WindowsCreateString(cls,(uint)cls.Length,out name));Guid iid=new Guid("2a59116d-6c4f-45e0-a74f-707e3fef9258");Check(RoGetActivationFactory(name,ref iid,out factory));
            if(write){if(target!=null)Check(WindowsCreateString(target,(uint)target.Length,out input));Check(Method<PolicySet>(factory,25)(factory,pid,flow,role,input));}
            Check(Method<PolicyGet>(factory,26)(factory,pid,flow,role,out output));uint length;return output==IntPtr.Zero?null:Marshal.PtrToStringUni(WindowsGetStringRawBuffer(output,out length),(int)length);
        }finally{if(output!=IntPtr.Zero)WindowsDeleteString(output);if(input!=IntPtr.Zero)WindowsDeleteString(input);Release(factory);if(name!=IntPtr.Zero)WindowsDeleteString(name);if(initialized>=0)RoUninitialize();}
    }
}
'@
}

function Select-QqAudioProcess($Items, [uint32[]]$ActivePids, [string]$InstallDir) {
    $matches = @($Items | Where-Object {
        $_.pid -gt 0 -and $_.created -gt 0 -and $_.app_error -eq 15703 -and $ActivePids -contains $_.pid -and
        $_.executable -ieq (Join-Path $InstallDir 'QQ\QQ.exe') -and
        $_.command_line.Contains((Join-Path $InstallDir 'runtime\av-host-profile'))
    })
    if ($matches.Count -ne 1) { throw 'Expected exactly one active QQ audio process without packaged application identity' }
    $matches[0]
}
function Assert-QqAudioSnapshot($Expected, $Actual) {
    if (-not $Actual -or $Expected.pid -ne $Actual.pid -or $Expected.created -ne $Actual.created -or
        $Expected.executable -ine $Actual.executable -or $Actual.app_error -ne 15703) { throw 'QQ audio process identity changed' }
}
function Select-QqAudioEndpoints($Devices, $Settings) {
    $names=@($Settings.native_output_device,$Settings.native_input_device)
    if ($names[0] -cne 'CABLE Input (VB-Audio Virtual Cable)' -or $names[1] -cne 'Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)') { throw 'Only the verified CABLE render and B1 capture buses are permitted' }
    $targets=@{}
    foreach($flow in @(0,1)) {
        $found=@($Devices | Where-Object { $_.Flow -eq $flow -and $_.Name -ceq $names[$flow] })
        if($found.Count -ne 1 -or -not $found[0].Id){throw 'Virtual audio endpoint is missing or ambiguous'}
        $targets[$flow]=$found[0]
    }
    $targets
}

function Set-QqAudioRoute {
    # shortcut: 仅验证本机 20348 x64 和两条虚拟线路，迁移机器时重新验收接口及端点。
    if ([Environment]::OSVersion.Version.Build -ne 20348 -or -not [Environment]::Is64BitProcess) { throw 'This route helper is verified only on Windows build 20348 x64' }
    $root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $runtime=Get-Content -LiteralPath (Join-Path $root 'data\voice_call\native-runtime.json') -Raw | ConvertFrom-Json
    $settings=Get-Content -LiteralPath (Join-Path $root 'data\voice_call\relay.json') -Raw | ConvertFrom-Json
    $install=(Resolve-Path -LiteralPath $runtime.install_dir).Path
    $hostUri=[Uri]$settings.host_url
    if ($hostUri.Scheme -ne 'http' -or -not $hostUri.IsLoopback -or $hostUri.UserInfo -or $hostUri.Query -or $hostUri.Fragment -or $hostUri.AbsolutePath -ne '/') { throw 'Audio prime requires the configured local Host' }
    $headers=@{Authorization='Bearer '+(Get-Content -LiteralPath $settings.control_token_file -Raw).Trim()}
    $devices=[YuexuIndependentAudio]::Devices()
    $targets=Select-QqAudioEndpoints $devices $settings
    $before=[YuexuIndependentAudio]::Defaults()
    for($flow=0;$flow -lt 2;$flow++){for($role=0;$role -lt 3;$role++){
        $expected=@($devices | Where-Object {$_.Flow -eq $flow -and $_.Id -eq $before[$flow*3+$role]})
        if($expected.Count -ne 1 -or $expected[0].Name -notlike '*Wuying ASP Audio*'){throw 'Caller default audio must be restored to Wuying before configuring independent QQ'}
    }}
    $report=[ordered]@{phase='prepared';scope='Persistent audio preference for the independent QQ application, shared by its processes; never for Codex';caller_defaults=$before;original_app=@()}
    $reportPath=Join-Path $root ('data\voice_call\verification\qq-audio-route-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fffffff')+'.json')
    $prime=$false;$snapshot=$null
    try {
        $prime=$true
        $receipt=Invoke-RestMethod -Method Post -Uri ($settings.host_url+'/v1/audio/prime') -Headers $headers -ContentType 'application/json' -Body '{"active":true}' -TimeoutSec 5
        if($receipt.code -ne 0){throw 'QQ audio prime was rejected'}
        $items=@()
        for($attempt=0;$attempt -lt 20;$attempt++) {
            $active=[YuexuIndependentAudio]::ActiveSessionPids()
            $items=@(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" | Where-Object {$active -contains $_.ProcessId -and $_.ExecutablePath -ieq (Join-Path $install 'QQ\QQ.exe')} | ForEach-Object {
                [pscustomobject]@{pid=$_.ProcessId;executable=$_.ExecutablePath;command_line=$_.CommandLine;created=$_.CreationDate.ToFileTimeUtc();app_error=[YuexuIndependentAudio]::AppIdentity($_.ProcessId)}
            })
            if(@($items | Where-Object {$_.command_line.Contains((Join-Path $install 'runtime\av-host-profile'))}).Count){break}
            Start-Sleep -Milliseconds 100
        }
        $snapshot=Select-QqAudioProcess $items $active $install
        $report.pid=$snapshot.pid;$report.executable=$snapshot.executable;$report.created=$snapshot.created
        foreach($flow in @(0,1)){foreach($role in @(0,1,2)){$report.original_app+=@{flow=$flow;role=$role;device=[YuexuIndependentAudio]::Preference($snapshot.pid,$flow,$role,$false,$null)}}}
        $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding utf8
        $actual=Get-CimInstance Win32_Process -Filter "ProcessId=$($snapshot.pid)"
        Assert-QqAudioSnapshot $snapshot ([pscustomobject]@{pid=$actual.ProcessId;executable=$actual.ExecutablePath;created=$actual.CreationDate.ToFileTimeUtc();app_error=[YuexuIndependentAudio]::AppIdentity($actual.ProcessId)})
        $interfaces=@('e6327cad-dcec-4949-ae8a-991e976a79d2','2eef81be-33fa-4800-9670-1cd474972c3f')
        $desired=@{}
        foreach($flow in @(0,1)){$desired[$flow]='\\?\SWD#MMDEVAPI#'+$targets[$flow].Id+'#{'+$interfaces[$flow]+'}'}
        $report.targets=@{render=$desired[0];capture=$desired[1]}
        foreach($flow in @(0,1)){foreach($role in @(0,1,2)){
            $current=[YuexuIndependentAudio]::Preference($snapshot.pid,$flow,$role,$false,$null)
            if($current -cne $desired[$flow]){$current=[YuexuIndependentAudio]::Preference($snapshot.pid,$flow,$role,$true,$desired[$flow])}
            if($current -cne $desired[$flow]){throw 'QQ application preference readback did not match'}
        }}
        if(@(Compare-Object $before ([YuexuIndependentAudio]::Defaults())).Count){throw 'Caller audio defaults changed while configuring independent QQ'}
        $report.phase='applied';$report.caller_defaults_unchanged=$true
    } catch {
        $failure=$_;$report.phase='failed';$report.rollback_confirmed=$false
        if($snapshot -and $report.original_app.Count -eq 6){
            $restored=$true
            foreach($old in $report.original_app){try{
                $current=[YuexuIndependentAudio]::Preference($snapshot.pid,$old.flow,$old.role,$false,$null)
                if($current -cne $old.device){$current=[YuexuIndependentAudio]::Preference($snapshot.pid,$old.flow,$old.role,$true,$old.device)}
                if($current -cne $old.device){$restored=$false}
            }catch{$restored=$false}}
            $report.rollback_confirmed=$restored
        }
        throw $failure
    } finally {
        if($prime){try{$cleanup=Invoke-RestMethod -Method Post -Uri ($settings.host_url+'/v1/audio/prime') -Headers $headers -ContentType 'application/json' -Body '{"active":false}' -TimeoutSec 5;$report.prime_cleanup_confirmed=$cleanup.code -eq 0}catch{$report.prime_cleanup_confirmed=$false}}
        $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding utf8
    }
    if(-not $report.prime_cleanup_confirmed){throw 'QQ silent audio prime cleanup was not confirmed'}
    [pscustomobject]@{phase=$report.phase;pid=$snapshot.pid;caller_defaults_unchanged=$report.caller_defaults_unchanged;report=$reportPath} | ConvertTo-Json -Compress
}
if ($MyInvocation.InvocationName -ne '.') { Set-QqAudioRoute }
