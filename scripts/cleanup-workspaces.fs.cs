// Windows-only no-follow pins and recoverable handle-bound same-volume rename.
// No ACL changes. Cache hardlinks require separate Git proof; other links fail closed.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace HealthCheck.WorkspaceCleanup {
    public sealed class Entry {
        public string Path; public bool Directory; public string Identity;
        public long Length; public DateTime Written; public uint Links;
        public string CacheRoot; public bool GeneratedCache;
        public string Stamp { get { return Identity + ":" + Length + ":" + Written.Ticks + ":" + Links; } }
    }
    public sealed class Tree : IDisposable {
        [StructLayout(LayoutKind.Sequential)] struct Info {
            public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written;
            public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        }
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security, uint mode, uint flags, IntPtr template);
        [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, StringBuilder name, uint size, uint flags);
        [DllImport("kernel32.dll", SetLastError=true)]
        static extern bool SetFileInformationByHandle(SafeFileHandle handle, int kind, IntPtr data, uint size);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool CreateDirectoryW(string path, IntPtr security);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        static extern bool MoveFileExW(string source, string target, uint flags);
        readonly Dictionary<string, SafeFileHandle> dirs = new Dictionary<string, SafeFileHandle>(StringComparer.OrdinalIgnoreCase);
        public readonly List<Entry> Entries = new List<Entry>();
        readonly Dictionary<string, Entry> entriesByPath = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
        readonly bool deleting;
        public Tree(bool deleteAccess) { deleting = deleteAccess; }
        static long Ticks(System.Runtime.InteropServices.ComTypes.FILETIME t) { return ((long)t.dwHighDateTime << 32) | (uint)t.dwLowDateTime; }
        static string Full(string path) { string full = System.IO.Path.GetFullPath(path); return full.Length == 3 ? full : full.TrimEnd('\\'); }
        static SafeFileHandle Open(string path, bool directory, uint access, uint share, uint mode) {
            var h = CreateFileW(path, access, share, IntPtr.Zero, mode, 0x00200000u | (directory ? 0x02000000u : 0u), IntPtr.Zero);
            if (h.IsInvalid) { h.Dispose(); throw new IOException("entry-unavailable"); }
            return h;
        }
        static Entry Inspect(string path, SafeFileHandle h, bool directory, bool cacheHardlink = false) {
            Info i;
            if (!GetFileInformationByHandle(h, out i) || (i.Attributes & 0x400) != 0 || ((i.Attributes & 0x10) != 0) != directory || (!directory && (i.Links == 0 || (i.Links != 1 && !cacheHardlink))))
                throw new IOException("unsafe-entry");
            var b = new StringBuilder(32768);
            uint size = GetFinalPathNameByHandleW(h, b, (uint)b.Capacity, 0);
            if (size == 0 || size >= b.Capacity || !String.Equals(b.ToString(), "\\\\?\\" + Full(path), StringComparison.OrdinalIgnoreCase))
                throw new IOException("aliased-entry");
            return new Entry { Path=Full(path), Directory=directory, Identity=i.Volume+":"+i.IndexHigh+":"+i.IndexLow,
                Length=((long)i.SizeHigh << 32) | i.SizeLow, Written=DateTime.FromFileTimeUtc(Ticks(i.Written)), Links=i.Links };
        }
        public void PinAncestors(string path) {
            string full = Full(path);
            string drive = System.IO.Path.GetPathRoot(full);
            if (drive.Length != 3 || drive[1] != ':') throw new IOException("nonlocal-path");
            string current = drive;
            // Include the volume root so all descendants are opened through pinned, real ancestors.
            foreach (string part in ("\\" + full.Substring(drive.Length)).Split('\\')) {
                if (part.Length > 0) current = System.IO.Path.Combine(current, part);
                string key = Full(current);
                if (!dirs.ContainsKey(key)) {
                    var h = Open(current, true, 0x80000000u, 3, 3);
                    try { Inspect(current, h, true); dirs.Add(key, h); } catch { h.Dispose(); throw; }
                }
            }
        }
        // Lexical candidates are not approval. Scan proves local no-follow topology;
        // PowerShell must subsequently prove ignored/untracked Git state for every entry.
        public static string GetCacheRoot(string workspace, string path, bool directory) {
            string root = Full(workspace), full = Full(path);
            if (!full.StartsWith(root + "\\", StringComparison.OrdinalIgnoreCase)) return null;
            string[] parts = full.Substring(root.Length + 1).Split('\\');
            if (String.Equals(parts[0], ".git", StringComparison.OrdinalIgnoreCase)) return null;
            if ((String.Equals(parts[0], ".venv", StringComparison.OrdinalIgnoreCase) ||
                 String.Equals(parts[0], ".pytest_cache", StringComparison.OrdinalIgnoreCase) ||
                 String.Equals(parts[0], ".ruff_cache", StringComparison.OrdinalIgnoreCase)) && (directory || parts.Length > 1))
                return System.IO.Path.Combine(root, parts[0]);
            string current = root;
            for (int i=0; i<parts.Length; i++) {
                current = System.IO.Path.Combine(current, parts[i]);
                if ((directory || i<parts.Length-1) && String.Equals(parts[i], "__pycache__", StringComparison.OrdinalIgnoreCase)) return current;
            }
            if (!directory && (full.EndsWith(".pyc", StringComparison.OrdinalIgnoreCase) || full.EndsWith(".pyo", StringComparison.OrdinalIgnoreCase))) return full;
            return null;
        }
        string workspace;
        bool observing;
        public void Scan(string path, int maximum) { workspace=Full(path); ScanNode(path, maximum, 0); }
        // Observation only: another retained root DELETE handle is compatible.
        // Descendants are still opened no-follow and directories pinned before enumeration.
        public void BindRootOnly(string path, string expectedIdentity) {
            if (!deleting || dirs.Count!=0 || Entries.Count!=0) throw new IOException("root-binding-required");
            workspace=Full(path);
            var h=Open(workspace,true,0x80000000u|0x10000u,3,3);
            try {
                var e=Inspect(workspace,h,true); dirs.Add(workspace,h); Entries.Add(e); entriesByPath.Add(workspace,e);
                if(HeldIdentity(workspace)!=expectedIdentity) throw new IOException("root-binding-changed");
            } catch { h.Dispose(); dirs.Clear(); Entries.Clear(); entriesByPath.Clear(); throw; }
        }
        public void ObserveBound(Tree binding, string path, string expectedIdentity, int maximum) {
            if(binding==null || !binding.deleting || binding.HeldIdentity(path)!=expectedIdentity) throw new IOException("root-binding-required");
            observing=true; workspace=Full(path); ScanNode(path,maximum,0);
        }
        public void ApproveGeneratedCache(string path, string stamp) {
            Entry entry;
            if (!entriesByPath.TryGetValue(path, out entry) || entry.CacheRoot == null || entry.Stamp != stamp) throw new IOException("cache-proof-changed");
            entry.GeneratedCache=true;
        }
        void ScanNode(string path, int maximum, int depth) {
            if (depth > 128) throw new IOException("tree-depth-limit");
            string full = Full(path);
            if (!dirs.ContainsKey(full)) {
                var h = Open(full, true, 0x80000000u | (deleting ? 0x10000u : 0u), observing && full==workspace ? 7u : 3u, 3);
                try {
                    var entry=Inspect(full, h, true); entry.CacheRoot=GetCacheRoot(workspace, full, true);
                    Entries.Add(entry); entriesByPath.Add(entry.Path, entry); dirs.Add(full, h);
                } catch { h.Dispose(); throw; }
            }
            if (Entries.Count > maximum) throw new IOException("tree-limit");
            foreach (string child in System.IO.Directory.GetFileSystemEntries(full)) {
                var attributes = File.GetAttributes(child);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("unsafe-entry");
                bool directory = (attributes & FileAttributes.Directory) != 0;
                if (directory) ScanNode(child, maximum, depth + 1);
                else {
                    using (var h = Open(child, false, 0x80000000u, 7, 3)) {
                        string cache=GetCacheRoot(workspace, child, false);
                        var entry=Inspect(child, h, false, cache != null); entry.CacheRoot=cache;
                        Entries.Add(entry); entriesByPath.Add(entry.Path, entry);
                    }
                    if (Entries.Count > maximum) throw new IOException("tree-limit");
                }
            }
        }
        public static string ReadGitPointer(string path) {
            using (var h = Open(path, false, 0x80000000u, 1, 3)) {
                var e = Inspect(path, h, false);
                if (e.Length > 4096) throw new IOException("metadata-limit");
                using (var stream = new FileStream(h, FileAccess.Read))
                using (var reader = new StreamReader(stream, Encoding.UTF8, true)) return reader.ReadToEnd().Trim();
            }
        }
        // Lifecycle state is outside the deletable checkout. All callers hold the
        // project mutex. Parent pins prevent path redirection; no ACL is changed.
        public static string IdentityOf(string path) {
            using (var h = Open(path, true, 0x80000000u, 7, 3)) {
                Entry e = Inspect(path, h, true); Info i;
                if (!GetFileInformationByHandle(h, out i)) throw new IOException("identity-unknown");
                return e.Identity + ":" + Ticks(i.Created);
            }
        }
        public static void CreateFresh(string path) {
            if (!CreateDirectoryW(path, IntPtr.Zero)) throw new IOException("workspace-exists-or-unavailable");
        }
        public static string StateKey(string path) {
            using (var hash = SHA256.Create()) {
                return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Full(path).ToUpperInvariant()))).Replace("-", "").ToLowerInvariant();
            }
        }
        public static string ReadState(string path) {
            using (var h = Open(path, false, 0x80000000u, 1, 3)) {
                if (Inspect(path, h, false).Length > 8192) throw new IOException("lifecycle-invalid");
                using (var stream = new FileStream(h, FileAccess.Read))
                using (var reader = new StreamReader(stream, new UTF8Encoding(false, true), false)) return reader.ReadToEnd();
            }
        }
        public static void WriteState(string path, string text, bool createOnly) { WriteAtomic(path,text,createOnly,8192); }
        public static void WriteObservation(string path, string text) { WriteAtomic(path,text,true,4194304); }
        static void WriteAtomic(string path, string text, bool createOnly, int limit) {
            byte[] bytes = new UTF8Encoding(false, true).GetBytes(text);
            if (bytes.Length > limit) throw new IOException("state-or-observation-limit");
            using (var pins = new Tree(false)) {
                pins.PinAncestors(System.IO.Path.GetDirectoryName(path));
                // Reject aliases/links even though replacement itself does not follow them.
                if (File.Exists(path) || Directory.Exists(path)) {
                    if (createOnly) throw new IOException("lifecycle-exists");
                    using (var h = Open(path, false, 0x80000000u, 1, 3)) Inspect(path, h, false);
                }
                string pending = path + ".pending-" + Guid.NewGuid().ToString("N");
                // An interrupted pending file is never authority, and never auto-applied.
                using (var h = Open(pending, false, 0xC0000000u, 0, 1)) {
                    Inspect(pending, h, false);
                    using (var stream = new FileStream(h, FileAccess.ReadWrite)) {
                        stream.Write(bytes, 0, bytes.Length); stream.Flush(true);
                    }
                }
                // Same-directory atomic rename, write-through; previous or new complete
                // record survives a process crash. No truncate-in-place transaction.
                if (!MoveFileExW(pending, path, (createOnly ? 0u : 1u) | 8u)) throw new IOException("lifecycle-write-failed");
            }
        }
        readonly List<SafeFileHandle> frozen = new List<SafeFileHandle>();
        bool relocationReady;
        string boundRootIdentity;
        string HeldIdentity(string path) {
            Info i;
            Inspect(path,dirs[workspace],true);
            if (!GetFileInformationByHandle(dirs[workspace],out i)) throw new IOException("identity-unknown");
            return i.Volume+":"+i.IndexHigh+":"+i.IndexLow+":"+Ticks(i.Created);
        }
        // Caller must persist intent and hold the lifecycle mutex BEFORE this call.
        // Only descendants are released; the verified root DELETE handle never closes.
        public void ReleaseDescendantsForRelocation(string expectedRootIdentity) {
            if (!deleting || relocationReady || HeldIdentity(workspace)!=expectedRootIdentity) throw new IOException("root-binding-changed");
            boundRootIdentity=expectedRootIdentity;
            foreach(var h in frozen) h.Dispose(); frozen.Clear();
            foreach(string path in new List<string>(dirs.Keys)) {
                if(path.StartsWith(workspace+"\\",StringComparison.OrdinalIgnoreCase)) { dirs[path].Dispose(); dirs.Remove(path); }
            }
            relocationReady=true;
        }
        // Freeze known files before journaling. Directory handles remain pinned.
        // This is cooperative lifecycle coordination, not a same-user security boundary.
        public void Freeze() {
            if (!deleting || frozen.Count != 0) throw new IOException("rename-not-enabled");
            try {
                foreach (var e in Entries) {
                    if (e.Directory) {
                        if (Inspect(e.Path, dirs[e.Path], true).Stamp != e.Stamp) throw new IOException("tree-changed");
                    } else {
                        var h=Open(e.Path, false, 0x80000000u, 1, 3);
                        frozen.Add(h);
                        if (Inspect(e.Path,h,false,e.GeneratedCache).Stamp != e.Stamp) throw new IOException("tree-changed");
                    }
                }
            } catch { foreach (var h in frozen) h.Dispose(); frozen.Clear(); throw; }
        }
        // No path-based source rename, replacement, copy/delete, Shell or fallback.
        // Source handle was acquired with DELETE while directories stayed pinned.
        public void RenameTo(string source, string destination) {
            source=Full(source); destination=Full(destination);
            if (!deleting || !relocationReady || HeldIdentity(source)!=boundRootIdentity ||
                !String.Equals(source,workspace,StringComparison.OrdinalIgnoreCase)) throw new IOException("rename-not-enabled");
            string parent=System.IO.Path.GetDirectoryName(destination), leaf=System.IO.Path.GetFileName(destination);
            if (leaf.Length==0 || leaf=="." || leaf==".." || leaf.IndexOfAny(new char[]{'\\','/',':'})>=0) throw new IOException("rename-target-invalid");
            using (var target=new Tree(false)) {
                target.PinAncestors(parent);
                Info si,di;
                if (!GetFileInformationByHandle(dirs[source],out si) || !GetFileInformationByHandle(target.dirs[Full(parent)],out di) || si.Volume!=di.Volume)
                    throw new IOException("rename-volume-mismatch");
                var drive=new DriveInfo(System.IO.Path.GetPathRoot(source));
                if (drive.DriveType!=DriveType.Fixed || drive.DriveFormat!="NTFS") throw new IOException("rename-context-rejected");
                Inspect(source,dirs[source],true);
                byte[] name=Encoding.Unicode.GetBytes(destination);
                int rootOffset=IntPtr.Size==8?8:4, lengthOffset=rootOffset+IntPtr.Size, nameOffset=lengthOffset+4;
                IntPtr buffer=Marshal.AllocHGlobal(nameOffset+name.Length+2);
                try {
                    for(int i=0;i<nameOffset+name.Length+2;i++) Marshal.WriteByte(buffer,i,0);
                    // FILE_RENAME_INFO: ReplaceIfExists=false, absolute target with all ancestors pinned.
                    Marshal.WriteIntPtr(buffer,rootOffset,IntPtr.Zero);
                    Marshal.WriteInt32(buffer,lengthOffset,name.Length); Marshal.Copy(name,0,IntPtr.Add(buffer,nameOffset),name.Length);
                    if (!SetFileInformationByHandle(dirs[source],3,buffer,(uint)(nameOffset+name.Length+2)))
                        throw new IOException("rename-refused-"+Marshal.GetLastWin32Error());
                    Info after;
                    if (!GetFileInformationByHandle(dirs[source],out after) || si.Volume!=after.Volume || si.IndexHigh!=after.IndexHigh || si.IndexLow!=after.IndexLow)
                        throw new IOException("rename-identity-unknown");
                    Inspect(destination,dirs[source],true);
                } finally { Marshal.FreeHGlobal(buffer); }
            }
        }
        public void Delete() { throw new IOException("permanent-delete-disabled"); }
        public static void WriteSummary(string path, string text) {
            byte[] bytes = new UTF8Encoding(false).GetBytes(text);
            if (bytes.Length > 262144) throw new IOException("report-limit");
            using (var h = Open(path, false, 0xC0000000u, 1, 4)) {
                Inspect(path, h, false);
                using (var stream = new FileStream(h, FileAccess.ReadWrite)) { stream.SetLength(0); stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            }
        }
        public void Dispose() { foreach (var h in frozen) h.Dispose(); frozen.Clear(); foreach (var h in dirs.Values) h.Dispose(); dirs.Clear(); }
    }
}
