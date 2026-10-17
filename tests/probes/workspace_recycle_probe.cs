// Synthetic-only Windows Shell feasibility probe. NEVER a janitor implementation.
// The sole public operation creates its own GUID fixture, recycles and restores it.
using System;
using System.IO;
using System.Text;
using System.Threading;
using System.Security.Principal;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace WorkspaceRecycleProbe {
    [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr ctx, ref Guid handler, ref Guid iid, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint kind, out IntPtr name);
        void GetAttributes(uint mask, out uint value);
        void Compare(IShellItem other, uint hint, out int order);
    }
    [ComImport, Guid("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileOperation {
        void Advise(IProgressSink sink, out uint cookie);
        void Unadvise(uint cookie);
        void SetOperationFlags(uint flags);
        void SetProgressMessage([MarshalAs(UnmanagedType.LPWStr)] string message);
        void SetProgressDialog(IntPtr dialog);
        void SetProperties(IntPtr properties);
        void SetOwnerWindow(uint hwnd);
        void ApplyPropertiesToItem(IShellItem item);
        void ApplyPropertiesToItems(IntPtr items);
        void RenameItem(IShellItem item, [MarshalAs(UnmanagedType.LPWStr)] string name, IProgressSink sink);
        void RenameItems(IntPtr items, [MarshalAs(UnmanagedType.LPWStr)] string name);
        void MoveItem(IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name, IProgressSink sink);
        void MoveItems(IntPtr items, IShellItem parent);
        void CopyItem(IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name, IProgressSink sink);
        void CopyItems(IntPtr items, IShellItem parent);
        void DeleteItem(IShellItem item, IProgressSink sink);
        void DeleteItems(IntPtr items);
        void NewItem(IShellItem parent, uint attributes, [MarshalAs(UnmanagedType.LPWStr)] string name, [MarshalAs(UnmanagedType.LPWStr)] string template, IProgressSink sink);
        void PerformOperations();
        void GetAnyOperationsAborted([MarshalAs(UnmanagedType.Bool)] out bool aborted);
    }
    [ComVisible(true), Guid("04b0f1a7-9490-44bc-96e1-4296a31252e2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IProgressSink {
        [PreserveSig] int StartOperations();
        [PreserveSig] int FinishOperations(int result);
        [PreserveSig] int PreRenameItem(uint flags, IShellItem item, [MarshalAs(UnmanagedType.LPWStr)] string name);
        [PreserveSig] int PostRenameItem(uint flags, IShellItem item, [MarshalAs(UnmanagedType.LPWStr)] string name, int result, IShellItem created);
        [PreserveSig] int PreMoveItem(uint flags, IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name);
        [PreserveSig] int PostMoveItem(uint flags, IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name, int result, IShellItem created);
        [PreserveSig] int PreCopyItem(uint flags, IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name);
        [PreserveSig] int PostCopyItem(uint flags, IShellItem item, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name, int result, IShellItem created);
        [PreserveSig] int PreDeleteItem(uint flags, IShellItem item);
        [PreserveSig] int PostDeleteItem(uint flags, IShellItem item, int result, IShellItem created);
        [PreserveSig] int PreNewItem(uint flags, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name);
        [PreserveSig] int PostNewItem(uint flags, IShellItem parent, [MarshalAs(UnmanagedType.LPWStr)] string name, [MarshalAs(UnmanagedType.LPWStr)] string template, uint attributes, int result, IShellItem created);
        [PreserveSig] int UpdateProgress(uint total, uint done);
        [PreserveSig] int ResetTimer();
        [PreserveSig] int PauseTimer();
        [PreserveSig] int ResumeTimer();
    }
    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    sealed class Sink : IProgressSink {
        internal const int Abort = unchecked((int)0x80004004);
        internal bool Veto, Restore, SawPre, SawPost;
        internal int ItemResult = Abort;
        internal IShellItem Recycled;
        internal string Original, ExpectedIdentity;
        internal uint TransferFlags;
        public int StartOperations() { return 0; }
        public int FinishOperations(int result) { return 0; }
        public int PreDeleteItem(uint flags, IShellItem item) {
            SawPre=true; TransferFlags=flags;
            // This is a test callback, not an atomic identity-bound filesystem action.
            if (Veto || Restore || (flags & 0x80) == 0) return Abort;
            try { return Probe.Identity(Original) == ExpectedIdentity ? 0 : Abort; } catch { return Abort; }
        }
        public int PostDeleteItem(uint flags, IShellItem item, int result, IShellItem created) {
            SawPost=true; ItemResult=result;
            if (result < 0 || created == null) return Abort;
            Recycled=created; return 0;
        }
        public int PreMoveItem(uint flags, IShellItem item, IShellItem parent, string name) {
            if (!Restore || Directory.Exists(Original) || File.Exists(Original) || (flags & 0x403) != 0) return Abort;
            return 0;
        }
        public int PostMoveItem(uint flags, IShellItem item, IShellItem parent, string name, int result, IShellItem created) { SawPost=true; ItemResult=result; return result < 0 ? Abort : 0; }
        public int PreRenameItem(uint f, IShellItem i, string n) { return Abort; }
        public int PostRenameItem(uint f, IShellItem i, string n, int r, IShellItem c) { return Abort; }
        public int PreCopyItem(uint f, IShellItem i, IShellItem p, string n) { return Abort; }
        public int PostCopyItem(uint f, IShellItem i, IShellItem p, string n, int r, IShellItem c) { return Abort; }
        public int PreNewItem(uint f, IShellItem p, string n) { return Abort; }
        public int PostNewItem(uint f, IShellItem p, string n, string t, uint a, int r, IShellItem c) { return Abort; }
        public int UpdateProgress(uint t, uint d) { return 0; }
        public int ResetTimer() { return 0; }
        public int PauseTimer() { return 0; }
        public int ResumeTimer() { return 0; }
    }
    public sealed class Result {
        public string Fixture, Volume, FileSystem, RootIdentityBefore, RootIdentityAfter;
        public bool VetoPreserved, PinnedPreserved, RecycledReceipt, Restored, ContentsEqual, IdentitiesEqual;
        public uint TransferFlags;
        public int PayloadBytes;
        public string Readiness = "SYNTHETIC_ONLY; PRODUCTION_IDENTITY_BINDING_UNRESOLVED";
    }
    public static class Probe {
        [StructLayout(LayoutKind.Sequential)] struct Info {
            public uint Attributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security, uint mode, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
        [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=true)]
        static extern int SHCreateItemFromParsingName(string path, IntPtr ctx, ref Guid iid, out IShellItem item);
        static readonly Guid ItemIid = new Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe");
        // No no-confirmation/overwrite/elevation flags on restore. Only recycle uses
        // no-confirmation, together with recycle-only intent and PreDelete veto.
        const uint Quiet = 0x4 | 0x400 | 0x00100000 | 0x00800000;
        static IShellItem Item(string path) {
            IShellItem item; Guid iid=ItemIid;
            Marshal.ThrowExceptionForHR(SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out item)); return item;
        }
        static IFileOperation Operation(uint flags) {
            IFileOperation op=(IFileOperation)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("3ad05575-8857-4850-9277-11b85bdb8e09")));
            op.SetOperationFlags(flags); return op;
        }
        static void Release(object value) { if (value != null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value); }
        internal static string Identity(string path) {
            using (SafeFileHandle h=CreateFileW(path,0x80000000u,7,IntPtr.Zero,3,0x00200000u | (Directory.Exists(path) ? 0x02000000u : 0),IntPtr.Zero)) {
                Info i;
                if (h.IsInvalid || !GetFileInformationByHandle(h,out i) || (i.Attributes & 0x400) != 0 || i.Links != 1) throw new IOException("probe-identity-unavailable");
                return i.Volume+":"+i.IndexHigh+":"+i.IndexLow+":"+i.Created.dwHighDateTime+":"+i.Created.dwLowDateTime;
            }
        }
        static void ValidateParent(string parent) {
            if (Thread.CurrentThread.GetApartmentState() != ApartmentState.STA || !Environment.UserInteractive || System.Diagnostics.Process.GetCurrentProcess().SessionId == 0) throw new IOException("probe-interactive-sta-required");
            if (new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) throw new IOException("probe-normal-user-required");
            string root=Path.GetPathRoot(parent);
            if (root.Length != 3 || root[1] != ':' || root[2] != '\\') throw new IOException("probe-local-volume-required");
            DriveInfo drive=new DriveInfo(root);
            if (drive.DriveType != DriveType.Fixed || drive.DriveFormat != "NTFS") throw new IOException("probe-fixed-ntfs-required");
            string current=parent;
            while (!String.IsNullOrEmpty(current)) {
                if (!Directory.Exists(current) || (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("probe-parent-rejected");
                DirectoryInfo info=Directory.GetParent(current); current=info == null ? null : info.FullName;
            }
        }
        static bool DeleteFixture(string fixture, Sink sink) {
            IFileOperation op=null; IShellItem item=null;
            try {
                op=Operation(Quiet | 0x10 | 0x00080000); item=Item(fixture);
                op.DeleteItem(item,sink); op.PerformOperations();
                bool aborted; op.GetAnyOperationsAborted(out aborted);
                return !aborted && sink.SawPre && sink.SawPost && sink.ItemResult >= 0 && sink.Recycled != null;
            } catch (COMException) { return false; }
            finally { Release(item); Release(op); }
        }
        public static Result Run(string fixtureParent) {
            string parent=Path.GetFullPath(fixtureParent).TrimEnd('\\');
            ValidateParent(parent);
            // Caller cannot supply an existing deletion target. There is no public
            // Recycle(path), permanent delete, bin enumeration or bin empty operation.
            string fixture=Path.Combine(parent,"workspace-recycle-probe-"+Guid.NewGuid().ToString("N"));
            if (Directory.Exists(fixture) || File.Exists(fixture)) throw new IOException("probe-collision");
            Directory.CreateDirectory(fixture);
            string payload=Path.Combine(fixture,"synthetic.txt");
            byte[] bytes=Encoding.UTF8.GetBytes("Synthetic workspace recycle round-trip. No Owner data.\r\n");
            if (bytes.Length > 4096) throw new IOException("probe-size-limit");
            using (FileStream file=new FileStream(payload,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { file.Write(bytes,0,bytes.Length); file.Flush(true); }
            Result result=new Result { Fixture=fixture, Volume=Path.GetPathRoot(fixture), FileSystem=new DriveInfo(Path.GetPathRoot(fixture)).DriveFormat, PayloadBytes=bytes.Length, RootIdentityBefore=Identity(fixture) };
            string fileIdentity=Identity(payload);
            Sink veto=new Sink { Veto=true, Original=fixture, ExpectedIdentity=result.RootIdentityBefore };
            bool vetoMoved=DeleteFixture(fixture,veto);
            result.VetoPreserved=!vetoMoved && veto.SawPre && Directory.Exists(fixture) && Identity(fixture)==result.RootIdentityBefore;
            if (!result.VetoPreserved) throw new IOException("probe-veto-failed; retain receipt and inspect only");
            // Demonstrate the production blocker: share=3 root pin prevents Shell.
            using (SafeFileHandle pin=CreateFileW(fixture,0x80000000u,3,IntPtr.Zero,3,0x02200000u,IntPtr.Zero)) {
                if (pin.IsInvalid) throw new IOException("probe-pin-unavailable");
                Sink locked=new Sink { Original=fixture, ExpectedIdentity=result.RootIdentityBefore };
                bool moved=DeleteFixture(fixture,locked);
                result.PinnedPreserved=!moved && Directory.Exists(fixture) && Identity(fixture)==result.RootIdentityBefore;
                if (!result.PinnedPreserved) throw new IOException("probe-pinned-assumption-failed; inspect only");
            }
            // Explicitly SYNTHETIC-only unpinned round-trip, never production claims.
            Sink recycle=new Sink { Original=fixture, ExpectedIdentity=result.RootIdentityBefore };
            result.RecycledReceipt=DeleteFixture(fixture,recycle);
            result.TransferFlags=recycle.TransferFlags;
            if (!result.RecycledReceipt || Directory.Exists(fixture) || File.Exists(fixture)) throw new IOException("probe-recycle-unverified; no fallback or retry");
            IFileOperation restore=null; IShellItem destination=null;
            try {
                if (Directory.Exists(fixture) || File.Exists(fixture)) throw new IOException("probe-restore-collision");
                restore=Operation(Quiet); destination=Item(parent);
                Sink sink=new Sink { Restore=true, Original=fixture };
                restore.MoveItem(recycle.Recycled,destination,Path.GetFileName(fixture),sink);
                restore.PerformOperations(); bool aborted; restore.GetAnyOperationsAborted(out aborted);
                if (aborted || !sink.SawPost || sink.ItemResult < 0) throw new IOException("probe-restore-unverified; retain recycled item");
                result.Restored=Directory.Exists(fixture) && File.Exists(payload);
                if (!result.Restored) throw new IOException("probe-restored-files-absent");
                result.RootIdentityAfter=Identity(fixture);
                result.IdentitiesEqual=result.RootIdentityAfter==result.RootIdentityBefore && Identity(payload)==fileIdentity;
                result.ContentsEqual=Convert.ToBase64String(File.ReadAllBytes(payload))==Convert.ToBase64String(bytes);
                if (!result.IdentitiesEqual || !result.ContentsEqual) throw new IOException("probe-roundtrip-mismatch");
                return result;
            } finally { Release(destination); Release(restore); Release(recycle.Recycled); }
            // Leave restored fixture for read-back. Never recursively delete it.
        }
    }
}
