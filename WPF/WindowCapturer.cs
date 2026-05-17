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

        private static double GetDpiScale(IntPtr hwnd)
        {
            try
            {
                uint dpi = GetDpiForWindow(hwnd);
                if (dpi > 0) return dpi / 96.0;
            }
            catch { }
            return 1.0;
        }

        public static byte[] Capture(string windowTitle, string mode, int[] rect)
        {
            IntPtr hwnd = FindWindow(null, windowTitle);
            if (hwnd == IntPtr.Zero)
            {
                Console.WriteLine($"[C# WindowCapturer] Window not found: {windowTitle}");
                return null;
            }

            if (IsIconic(hwnd))
            {
                Console.WriteLine($"[C# WindowCapturer] Window is minimized: {windowTitle}");
                return null;
            }

            double scale = GetDpiScale(hwnd);

            // クライアント領域のサイズを取得
            RECT clientRect;
            if (!GetClientRect(hwnd, out clientRect)) return null;

            int w = clientRect.Right - clientRect.Left;
            int h = clientRect.Bottom - clientRect.Top;

            POINT pt = new POINT { X = 0, Y = 0 };
            ClientToScreen(hwnd, ref pt);

            int left = pt.X;
            int top = pt.Y;

            // 部分領域の指定がある場合
            if (rect != null && rect.Length >= 4)
            {
                // Pythonから渡されるのは クライアント領域内の相対座標(x, y, w, h)
                // 絶対スクリーン座標に加算して物理ピクセルへ変換する
                left += rect[0];
                top += rect[1];
                w = rect[2];
                h = rect[3];
            }

            int pLeft = (int)Math.Round(left * scale);
            int pTop = (int)Math.Round(top * scale);
            int pW = (int)Math.Round(w * scale);
            int pH = (int)Math.Round(h * scale);

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

            SelectObject(saveDC, oldBmp);
            DeleteObject(saveBitMap);
            DeleteDC(saveDC);
            ReleaseDC(hwndDesktop, hwndDC);

            return bytes;
        }

        private static byte[] CapturePrintWindow(IntPtr hwnd, int pW, int pH)
        {
            IntPtr hwndDC = GetWindowDC(hwnd);
            IntPtr saveDC = CreateCompatibleDC(hwndDC);
            IntPtr saveBitMap = CreateCompatibleBitmap(hwndDC, pW, pH);
            IntPtr oldBmp = SelectObject(saveDC, saveBitMap);

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

            SelectObject(saveDC, oldBmp);
            DeleteObject(saveBitMap);
            DeleteDC(saveDC);
            ReleaseDC(hwnd, hwndDC);

            return bytes;
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
