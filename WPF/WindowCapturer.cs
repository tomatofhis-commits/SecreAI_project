using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;

namespace RTtranslator_CS_Overlay
{
    public static class WindowCapturer
    {
        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool ClientToScreen(IntPtr hWnd, ref POINT lpPoint);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr GetWindowDC(IntPtr hWnd);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern int ReleaseDC(IntPtr hWnd, IntPtr hDC);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern IntPtr GetDesktopWindow();

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint GetDpiForWindow(IntPtr hWnd);

        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr CreateCompatibleDC(IntPtr hDC);

        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr CreateCompatibleBitmap(IntPtr hDC, int nWidth, int nHeight);

        [DllImport("gdi32.dll", SetLastError = true)]
        private static extern IntPtr SelectObject(IntPtr hDC, IntPtr hObject);

        [DllImport("gdi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteDC(IntPtr hDC);

        [DllImport("gdi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool DeleteObject(IntPtr hObject);

        [DllImport("gdi32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool BitBlt(IntPtr hObject, int nXDest, int nYDest, int nWidth, int nHeight, IntPtr hObjSource, int nXSrc, int nYSrc, int dwRop);

        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);

        private const int SRCCOPY = 0x00CC0020;

        [StructLayout(LayoutKind.Sequential)]
        private struct RECT
        {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct POINT
        {
            public int X;
            public int Y;
        }

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder strText, int maxCount);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowTextLength(IntPtr hWnd);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        private static IntPtr FindWindowPartial(string title)
        {
            IntPtr foundHwnd = IntPtr.Zero;
            EnumWindows(delegate (IntPtr hWnd, IntPtr lParam)
            {
                if (IsWindowVisible(hWnd))
                {
                    int size = GetWindowTextLength(hWnd);
                    if (size > 0)
                    {
                        System.Text.StringBuilder sb = new System.Text.StringBuilder(size + 1);
                        GetWindowText(hWnd, sb, sb.Capacity);
                        string wTitle = sb.ToString();
                        if (wTitle.ToLower().Contains(title.ToLower()))
                        {
                            foundHwnd = hWnd;
                            return false; // Stop enumeration
                        }
                    }
                }
                return true; // Continue enumeration
            }, IntPtr.Zero);
            return foundHwnd;
        }

        private static double GetDpiScale(IntPtr hwnd)
        {
            try
            {
                uint dpi = GetDpiForWindow(hwnd);
                if (dpi > 0) return dpi / 96.0;
            }
            catch { }
            try
            {
                using (Graphics g = Graphics.FromHwnd(IntPtr.Zero))
                {
                    return g.DpiX / 96.0;
                }
            }
            catch { }
            return 1.0;
        }

        public static byte[] Capture(string windowTitle, string mode, int[] rect)
        {
            IntPtr hwnd = FindWindow(null, windowTitle);
            if (hwnd == IntPtr.Zero)
            {
                hwnd = FindWindowPartial(windowTitle);
            }
            if (hwnd == IntPtr.Zero)
            {
                Console.WriteLine(string.Format("[C# WindowCapturer] Window not found: {0}", windowTitle));
                return null;
            }

            if (IsIconic(hwnd))
            {
                Console.WriteLine(string.Format("[C# WindowCapturer] Window is minimized: {0}", windowTitle));
                return null;
            }

            double scale = GetDpiScale(hwnd);

            // クライアント領域のサイズを取得
            RECT clientRect;
            if (!GetClientRect(hwnd, out clientRect)) return null;

            // DPI-awareプロセスなので、GetClientRectとClientToScreenで得られるのは物理座標です
            int w = clientRect.Right - clientRect.Left;
            int h = clientRect.Bottom - clientRect.Top;

            POINT pt = new POINT { X = 0, Y = 0 };
            ClientToScreen(hwnd, ref pt);

            int pLeft = pt.X;
            int pTop = pt.Y;
            int pW = w;
            int pH = h;

            // 部分領域の指定がある場合
            if (rect != null && rect.Length >= 4)
            {
                // Python(DPI-unaware)から渡される相対座標(論理)を物理座標にスケーリングして加算
                pLeft += (int)Math.Round(rect[0] * scale);
                pTop += (int)Math.Round(rect[1] * scale);
                pW = (int)Math.Round(rect[2] * scale);
                pH = (int)Math.Round(rect[3] * scale);
            }

            if (pW <= 0 || pH <= 0) return null;

            if (mode == "bitblt")
            {
                return CaptureBitBlt(pLeft, pTop, pW, pH);
            }
            else if (mode == "printwindow")
            {
                return CapturePrintWindow(hwnd, pW, pH);
            }
            else if (mode == "screen" || mode == "mss")
            {
                return CaptureScreen(pLeft, pTop, pW, pH);
            }
            else if (mode == "wgc" || mode == "dxcam")
            {
                Console.WriteLine("[C# WindowCapturer] WGC/DXCAM mode is not implemented in C# overlay server. Falling back to Python.");
                return null;
            }

            // デフォルトは bitblt
            return CaptureBitBlt(pLeft, pTop, pW, pH);
        }

        private static byte[] CaptureBitBlt(int pLeft, int pTop, int pW, int pH)
        {
            IntPtr hwndDesktop = GetDesktopWindow();
            IntPtr hwndDC = GetWindowDC(hwndDesktop);
            IntPtr saveDC = CreateCompatibleDC(hwndDC);
            IntPtr saveBitMap = CreateCompatibleBitmap(hwndDC, pW, pH);
            IntPtr oldBmp = SelectObject(saveDC, saveBitMap);

            try
            {
                bool success = BitBlt(saveDC, 0, 0, pW, pH, hwndDC, pLeft, pTop, SRCCOPY);

                byte[] bytes = null;
                if (success)
                {
                    using (Bitmap bmp = Bitmap.FromHbitmap(saveBitMap))
                    {
                        using (MemoryStream ms = new MemoryStream())
                        {
                            bmp.Save(ms, ImageFormat.Png);
                            bytes = ms.ToArray();
                        }
                    }
                }
                return bytes;
            }
            finally
            {
                SelectObject(saveDC, oldBmp);
                DeleteObject(saveBitMap);
                DeleteDC(saveDC);
                ReleaseDC(hwndDesktop, hwndDC);
            }
        }

        private static byte[] CapturePrintWindow(IntPtr hwnd, int pW, int pH)
        {
            IntPtr hwndDC = GetWindowDC(hwnd);
            IntPtr saveDC = CreateCompatibleDC(hwndDC);
            IntPtr saveBitMap = CreateCompatibleBitmap(hwndDC, pW, pH);
            IntPtr oldBmp = SelectObject(saveDC, saveBitMap);

            try
            {
                // Flags: 1 = PW_CLIENTONLY
                bool success = PrintWindow(hwnd, saveDC, 1);

                byte[] bytes = null;
                if (success)
                {
                    using (Bitmap bmp = Bitmap.FromHbitmap(saveBitMap))
                    {
                        using (MemoryStream ms = new MemoryStream())
                        {
                            bmp.Save(ms, ImageFormat.Png);
                            bytes = ms.ToArray();
                        }
                    }
                }
                return bytes;
            }
            finally
            {
                SelectObject(saveDC, oldBmp);
                DeleteObject(saveBitMap);
                DeleteDC(saveDC);
                ReleaseDC(hwnd, hwndDC);
            }
        }

        private static byte[] CaptureScreen(int pLeft, int pTop, int pW, int pH)
        {
            using (Bitmap bmp = new Bitmap(pW, pH))
            {
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.CopyFromScreen(pLeft, pTop, 0, 0, new Size(pW, pH), CopyPixelOperation.SourceCopy);
                }
                using (MemoryStream ms = new MemoryStream())
                {
                    bmp.Save(ms, ImageFormat.Png);
                    return ms.ToArray();
                }
            }
        }
    }
}
