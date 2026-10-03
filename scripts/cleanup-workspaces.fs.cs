// Windows-only no-follow directory pins and handle-bound standalone deletion.
// No ACL changes; a new/unreadable/reparse/hardlinked entry fails closed.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace HealthCheck.WorkspaceCleanup {
    public sealed class Entry {
        public string Path; public bool Directory; public string Identity;
        public long Length; public DateTime Written;
        public string Stamp { get { return Identity + ":" + Length + ":" + Written.Ticks; } }
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
        static extern bool SetFileInformationByHandle(SafeFileHandle handle, int kind, ref uint flags, uint size);
        readonly Dictionary<string, SafeFileHandle> dirs = new Dictionary<string, SafeFileHandle>(StringComparer.OrdinalIgnoreCase);
        public readonly List<Entry> Entries = new List<Entry>();
        readonly bool deleting;
        public Tree(bool deleteAccess) { deleting = deleteAccess; }
        static long Ticks(System.Runtime.InteropServices.ComTypes.FILETIME t) { return ((long)t.dwHighDateTime << 32) | (uint)t.dwLowDateTime; }
        static string Full(string path) { string full = System.IO.Path.GetFullPath(path); return full.Length == 3 ? full : full.TrimEnd('\\'); }
        static SafeFileHandle Open(string path, bool directory, uint access, uint share, uint mode) {
            var h = CreateFileW(path, access, share, IntPtr.Zero, mode, 0x00200000u | (directory ? 0x02000000u : 0u), IntPtr.Zero);
            if (h.IsInvalid) { h.Dispose(); throw new IOException("entry-unavailable"); }
            return h;
        }
        static Entry Inspect(string path, SafeFileHandle h, bool directory) {
            Info i;
            if (!GetFileInformationByHandle(h, out i) || (i.Attributes & 0x400) != 0 || ((i.Attributes & 0x10) != 0) != directory || (!directory && i.Links != 1))
                throw new IOException("unsafe-entry");
            var b = new StringBuilder(32768);
            uint size = GetFinalPathNameByHandleW(h, b, (uint)b.Capacity, 0);
            if (size == 0 || size >= b.Capacity || !String.Equals(b.ToString(), "\\\\?\\" + Full(path), StringComparison.OrdinalIgnoreCase))
                throw new IOException("aliased-entry");
            return new Entry { Path=Full(path), Directory=directory, Identity=i.Volume+":"+i.IndexHigh+":"+i.IndexLow,
                Length=((long)i.SizeHigh << 32) | i.SizeLow, Written=DateTime.FromFileTimeUtc(Ticks(i.Written)) };
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
        public void Scan(string path, int maximum) { ScanNode(path, maximum, 0); }
        void ScanNode(string path, int maximum, int depth) {
            if (depth > 128) throw new IOException("tree-depth-limit");
            string full = Full(path);
            if (!dirs.ContainsKey(full)) {
                var h = Open(full, true, 0x80000000u | (deleting ? 0x10000u : 0u), 3, 3);
                try { Entries.Add(Inspect(full, h, true)); dirs.Add(full, h); } catch { h.Dispose(); throw; }
            }
            if (Entries.Count > maximum) throw new IOException("tree-limit");
            foreach (string child in System.IO.Directory.GetFileSystemEntries(full)) {
                var attributes = File.GetAttributes(child);
                if ((attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("unsafe-entry");
                bool directory = (attributes & FileAttributes.Directory) != 0;
                if (directory) ScanNode(child, maximum, depth + 1);
                else {
                    using (var h = Open(child, false, 0x80000000u, 7, 3)) Entries.Add(Inspect(child, h, false));
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
        // Scan pins every directory. Freeze all known files and compare before marking any for deletion.
        // Directory disposition can fail on a concurrently added file; that file is never followed/deleted.
        public void Delete() {
            if (!deleting) throw new IOException("delete-not-enabled");
            var files = new List<SafeFileHandle>();
            int marked = 0;
            try {
                foreach (var e in Entries) if (!e.Directory) {
                    var h = Open(e.Path, false, 0x80000000u | 0x10000u, 1, 3);
                    files.Add(h);
                    if (Inspect(e.Path, h, false).Stamp != e.Stamp) throw new IOException("tree-changed");
                }
                uint flags = 0x11; // FILE_DISPOSITION_DELETE | IGNORE_READONLY_ATTRIBUTE; Windows 10+.
                foreach (var h in files) {
                    if (!SetFileInformationByHandle(h, 21, ref flags, 4)) throw new IOException("delete-failed");
                    marked++;
                }
            } catch {
                uint clear = 0;
                for (int i=0; i<marked; i++) SetFileInformationByHandle(files[i], 21, ref clear, 4);
                throw;
            } finally { foreach (var h in files) h.Dispose(); }
            for (int i=Entries.Count-1; i>=0; i--) if (Entries[i].Directory) {
                string path = Entries[i].Path;
                uint flags = 0x11;
                if (!SetFileInformationByHandle(dirs[path], 21, ref flags, 4)) throw new IOException("delete-failed");
                dirs[path].Dispose(); dirs.Remove(path);
            }
        }
        public static void WriteSummary(string path, string text) {
            byte[] bytes = new UTF8Encoding(false).GetBytes(text);
            if (bytes.Length > 262144) throw new IOException("report-limit");
            using (var h = Open(path, false, 0xC0000000u, 1, 4)) {
                Inspect(path, h, false);
                using (var stream = new FileStream(h, FileAccess.ReadWrite)) { stream.SetLength(0); stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            }
        }
        public void Dispose() { foreach (var h in dirs.Values) h.Dispose(); dirs.Clear(); }
    }
}
