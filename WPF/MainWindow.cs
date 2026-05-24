using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;

namespace RTtranslator_CS_Overlay
{
    public class MainWindow : Window
    {
        // --- Win32 P/Invokes for Click-Through & Focus-Avoidance ---
        [DllImport("user32.dll")]
        private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll")]
        private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

        [DllImport("user32.dll")]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        private const int GWL_EXSTYLE = -20;
        private const int WS_EX_TRANSPARENT = 0x00000020;
        private const int WS_EX_NOACTIVATE = 0x08000000;

        private static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        private const uint SWP_NOMOVE = 0x0002;
        private const uint SWP_NOSIZE = 0x0001;
        private const uint SWP_NOACTIVATE = 0x0010;
        private const uint SWP_SHOWWINDOW = 0x0040;

        // --- UI Canvas ---
        public Canvas OverlayCanvas { get; private set; }
        private Border _statusBorder;
        private TextBlock _statusTextBlock;

        // --- HTTP API Listener ---
        private HttpListener _httpListener;
        private Thread _listenerThread;
        private bool _isRunning = false;

        // --- Overlay Tracking Dictionary ---
        private readonly Dictionary<string, Border> _activeOverlays = new Dictionary<string, Border>();
        private double _dpiScale = 1.0;

        public MainWindow()
        {
            this.Title = "RTtranslator CS Overlay";
            this.WindowStyle = WindowStyle.None;
            this.AllowsTransparency = true;
            this.Background = Brushes.Transparent;
            this.Topmost = true;
            this.ShowInTaskbar = false;

            // Set size to cover all monitors (Virtual Screen bounds)
            this.Left = SystemParameters.VirtualScreenLeft;
            this.Top = SystemParameters.VirtualScreenTop;
            this.Width = SystemParameters.VirtualScreenWidth;
            this.Height = SystemParameters.VirtualScreenHeight;

            // Create Canvas and add to window content
            OverlayCanvas = new Canvas
            {
                Background = Brushes.Transparent,
                Width = this.Width,
                Height = this.Height
            };
            this.Content = OverlayCanvas;

            // Create Status UI (PyQt 側のデザインを 100% 美麗に再現)
            _statusTextBlock = new TextBlock
            {
                Text = "⏳ 待機中...",
                Foreground = new SolidColorBrush(Color.FromRgb(0, 255, 0)), // #00FF00
                FontSize = 13,
                FontWeight = FontWeights.Bold,
                FontFamily = new FontFamily("Yu Gothic UI"),
                Padding = new Thickness(10, 4, 10, 4),
                VerticalAlignment = VerticalAlignment.Center
            };

            _statusBorder = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(178, 0, 0, 0)), // rgba(0,0,0,0.7)
                BorderBrush = new SolidColorBrush(Color.FromArgb(76, 0, 255, 0)), // rgba(0,255,0,0.3)
                BorderThickness = new Thickness(0, 0, 0, 1),
                Height = 28,
                Child = _statusTextBlock,
                Visibility = Visibility.Collapsed // 初期状態は非表示
            };

            OverlayCanvas.Children.Add(_statusBorder);

            this.Loaded += Window_Loaded;
            this.Closed += Window_Closed;


            // Start checking parent process lifetime if a PID is passed
            var args = Environment.GetCommandLineArgs();
            int parentPid;
            if (args.Length > 1 && int.TryParse(args[1], out parentPid))
            {
                StartParentProcessMonitor(parentPid);
            }
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);

            // Hook window styles via Win32 to make it click-through and non-activatable (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            var hwnd = new WindowInteropHelper(this).Handle;
            int extendedStyle = GetWindowLong(hwnd, GWL_EXSTYLE);
            SetWindowLong(hwnd, GWL_EXSTYLE, extendedStyle | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE);

            // Enforce static topmost Z-Order to avoid window focus freeze issues
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
        }

        private void Window_Loaded(object sender, RoutedEventArgs e)
        {
            // Acquire current OS display DPI scaling factor (e.g. 1.5 for 150%, 2.0 for 200%)
            var source = PresentationSource.FromVisual(this);
            if (source != null && source.CompositionTarget != null)
            {
                _dpiScale = source.CompositionTarget.TransformToDevice.M11;
            }

            // Start local HTTP Server on background thread
            StartHttpServer();
        }

        private void Window_Closed(object sender, EventArgs e)
        {
            StopHttpServer();
        }

        private void StartParentProcessMonitor(int parentPid)
        {
            var thread = new Thread(() =>
            {
                while (true)
                {
                    try
                    {
                        var parent = System.Diagnostics.Process.GetProcessById(parentPid);
                        if (parent == null || parent.HasExited)
                        {
                            Dispatcher.Invoke(new Action(() => this.Close()));
                            break;
                        }
                    }
                    catch
                    {
                        Dispatcher.Invoke(new Action(() => this.Close()));
                        break;
                    }
                    Thread.Sleep(1500);
                }
            })
            {
                IsBackground = true
            };
            thread.Start();
        }

        // --- HTTP API Server Implementation ---
        private void StartHttpServer()
        {
            _isRunning = true;
            _httpListener = new HttpListener();
            _httpListener.Prefixes.Add("http://127.0.0.1:5002/");

            try
            {
                _httpListener.Start();

                _listenerThread = new Thread(ListenLoop)
                {
                    IsBackground = true
                };
                _listenerThread.Start();
            }
            catch (Exception ex)
            {
                MessageBox.Show(string.Format("Failed to start local C# API server on port 5002:\n{0}", ex.Message), "RTT Overlay Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void StopHttpServer()
        {
            _isRunning = false;
            if (_httpListener != null)
            {
                try
                {
                    _httpListener.Stop();
                    _httpListener.Close();
                }
                catch { }
            }
        }

        private void ListenLoop()
        {
            while (_isRunning)
            {
                try
                {
                    var context = _httpListener.GetContext();
                    ThreadPool.QueueUserWorkItem((state) => HandleRequest((HttpListenerContext)state), context);
                }
                catch
                {
                    if (!_isRunning) break;
                }
            }
        }

        private void HandleRequest(HttpListenerContext context)
        {
            var req = context.Request;
            var resp = context.Response;

            resp.Headers.Add("Access-Control-Allow-Origin", "*");
            resp.Headers.Add("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
            resp.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

            if (req.HttpMethod == "OPTIONS")
            {
                resp.StatusCode = (int)HttpStatusCode.OK;
                resp.Close();
                return;
            }

            try
            {
                string path = req.Url.AbsolutePath.ToLower();
                if (path == "/api/status" && req.HttpMethod == "GET")
                {
                    SendJsonResponse(resp, new { status = "ok", message = "RTT C# Overlay Running" });
                }
                else if (path == "/api/update" && req.HttpMethod == "POST")
                {
                    using (var reader = new StreamReader(req.InputStream, Encoding.UTF8))
                    {
                        string body = reader.ReadToEnd();
                        var serializer = new JavaScriptSerializer();
                        var payload = serializer.Deserialize<OverlayUpdatePayload>(body);

                        if (payload != null)
                        {
                            // Dispatch UI updates to WPF main thread
                            Dispatcher.Invoke(new Action(() => SyncOverlays(payload.overlays)));
                            SendJsonResponse(resp, new { status = "ok" });
                        }
                        else
                        {
                            SendErrorResponse(resp, HttpStatusCode.BadRequest, "Invalid JSON payload");
                        }
                    }
                }
                else if (path == "/api/clear" && req.HttpMethod == "POST")
                {
                    Dispatcher.Invoke(new Action(() => ClearAllOverlays()));
                    SendJsonResponse(resp, new { status = "ok" });
                }
                else if (path == "/api/capture" && req.HttpMethod == "POST")
                {
                    using (var reader = new StreamReader(req.InputStream, Encoding.UTF8))
                    {
                        string body = reader.ReadToEnd();
                        var serializer = new JavaScriptSerializer();
                        var payload = serializer.Deserialize<CaptureRequestPayload>(body);

                        if (payload != null && !string.IsNullOrEmpty(payload.window_title))
                        {
                            byte[] imgBytes = WindowCapturer.Capture(payload.window_title, payload.mode ?? "bitblt", payload.rect);
                            if (imgBytes != null && imgBytes.Length > 0)
                            {
                                resp.ContentType = "image/png";
                                resp.ContentLength64 = imgBytes.Length;
                                resp.StatusCode = (int)HttpStatusCode.OK;
                                resp.OutputStream.Write(imgBytes, 0, imgBytes.Length);
                                resp.Close();
                            }
                            else
                            {
                                SendErrorResponse(resp, HttpStatusCode.InternalServerError, "Failed to capture window");
                            }
                        }
                        else
                        {
                            SendErrorResponse(resp, HttpStatusCode.BadRequest, "Invalid capture payload");
                        }
                    }
                }
                else if (path == "/api/set_status" && req.HttpMethod == "POST")
                {
                    using (var reader = new StreamReader(req.InputStream, Encoding.UTF8))
                    {
                        string body = reader.ReadToEnd();
                        var serializer = new JavaScriptSerializer();
                        var payload = serializer.Deserialize<StatusUpdatePayload>(body);
                        if (payload != null)
                        {
                            Dispatcher.Invoke(new Action(() => UpdateStatusUI(payload)));
                            SendJsonResponse(resp, new { status = "ok" });
                        }
                        else
                        {
                            SendErrorResponse(resp, HttpStatusCode.BadRequest, "Invalid status payload");
                        }
                    }
                }
                else if (path == "/api/stop" && req.HttpMethod == "POST")
                {
                    SendJsonResponse(resp, new { status = "ok", message = "Stopping application" });
                    Dispatcher.Invoke(new Action(() => this.Close()));
                }
                else
                {
                    SendErrorResponse(resp, HttpStatusCode.NotFound, "Not Found");
                }
            }
            catch (Exception ex)
            {
                SendErrorResponse(resp, HttpStatusCode.InternalServerError, ex.Message);
            }
        }

        private void SendJsonResponse(HttpListenerResponse resp, object data)
        {
            var serializer = new JavaScriptSerializer();
            string json = serializer.Serialize(data);
            byte[] buf = Encoding.UTF8.GetBytes(json);

            resp.ContentType = "application/json; charset=utf-8";
            resp.ContentLength64 = buf.Length;
            resp.StatusCode = (int)HttpStatusCode.OK;
            resp.OutputStream.Write(buf, 0, buf.Length);
            resp.Close();
        }

        private void SendErrorResponse(HttpListenerResponse resp, HttpStatusCode code, string message)
        {
            var data = new { status = "error", message = message };
            var serializer = new JavaScriptSerializer();
            string json = serializer.Serialize(data);
            byte[] buf = Encoding.UTF8.GetBytes(json);

            resp.ContentType = "application/json; charset=utf-8";
            resp.ContentLength64 = buf.Length;
            resp.StatusCode = (int)code;
            resp.OutputStream.Write(buf, 0, buf.Length);
            resp.Close();
        }

        // --- Helper Methods for Layout & Typography Optimization ---
        private Brush GetContrastTextBrush(Brush textBrush, Brush bgBrush)
        {
            Color tc = Colors.White;
            Color bgc = Color.FromArgb(160, 0, 0, 0); // Default dark

            SolidColorBrush stb = textBrush as SolidColorBrush;
            if (stb != null) tc = stb.Color;

            SolidColorBrush sbg = bgBrush as SolidColorBrush;
            if (sbg != null) bgc = sbg.Color;

            // Calculate relative luminance (Y = 0.299R + 0.587G + 0.114B)
            double tl = 0.299 * tc.R + 0.587 * tc.G + 0.114 * tc.B;
            double bgl = 0.299 * bgc.R + 0.587 * bgc.G + 0.114 * bgc.B;

            // If text is dark (luminance < 90) and background is also dark, force text to White
            if (tl < 90)
            {
                if (bgl < 120 || bgc.A < 180)
                {
                    return Brushes.White;
                }
            }
            // If both are extremely bright and alpha is opaque, force text to Black
            else if (tl > 180 && bgl > 180 && bgc.A > 150)
            {
                return Brushes.Black;
            }

            return textBrush;
        }

        private double MeasureTextWidth(string text, double fontSize, FontFamily fontFamily)
        {
            var formattedText = new FormattedText(
                text,
                CultureInfo.CurrentUICulture,
                FlowDirection.LeftToRight,
                new Typeface(fontFamily, FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                fontSize,
                Brushes.Black);
            return formattedText.Width;
        }

        private double MeasureTextHeight(string text, double fontSize, FontFamily fontFamily, double maxWidth)
        {
            var formattedText = new FormattedText(
                text,
                CultureInfo.CurrentUICulture,
                FlowDirection.LeftToRight,
                new Typeface(fontFamily, FontStyles.Normal, FontWeights.Bold, FontStretches.Normal),
                fontSize,
                Brushes.Black);
            if (maxWidth > 0)
            {
                formattedText.MaxTextWidth = maxWidth;
            }
            return formattedText.Height;
        }

        // --- Core UI Synchronization (WPF Thread only) ---
        private void SyncOverlays(List<OverlayItem> incomingItems)
        {

            if (incomingItems == null) incomingItems = new List<OverlayItem>();

            var processedIds = new HashSet<string>();

            double vLeft = SystemParameters.VirtualScreenLeft;
            double vTop = SystemParameters.VirtualScreenTop;

            foreach (var item in incomingItems)
            {
                if (string.IsNullOrEmpty(item.id)) continue;

                processedIds.Add(item.id);

                // OSのDPIスケーリングに合わせて、受信したすべての物理ピクセル寸法をWPFの論理ピクセルにデスケール補正する
                double logicalX = item.x / _dpiScale;
                double logicalY = item.y / _dpiScale;
                double logicalWidth = item.width / _dpiScale;
                double logicalHeight = item.height / _dpiScale;
                double logicalFontSize = (item.font_size > 0 ? item.font_size : 14) / _dpiScale;

                // Align coordinates relative to our full-screen Canvas positioned at (vLeft, vTop)
                double relativeX = logicalX - vLeft;
                double relativeY = logicalY - vTop;

                // Configure styling properties
                Brush textBrush = Brushes.White;
                if (!string.IsNullOrEmpty(item.font_color))
                {
                    try
                    {
                        textBrush = (Brush)new BrushConverter().ConvertFromString(item.font_color);
                    }
                    catch { }
                }

                Brush bgBrush = new SolidColorBrush(Color.FromArgb(160, 0, 0, 0)); // Translucent black background by default
                if (!string.IsNullOrEmpty(item.bg_color))
                {
                    try
                    {
                        bgBrush = (Brush)new BrushConverter().ConvertFromString(item.bg_color);
                    }
                    catch { }
                }

                // Apply dynamic contrast fallbacks to ensure readability (Anti black-on-black logic)
                textBrush = GetContrastTextBrush(textBrush, bgBrush);

                // Auto-scale font size dynamically to fit the text bounding box (Overflow prevention)
                double finalFontSize = logicalFontSize;
                FontFamily fontFamily = new FontFamily("Yu Gothic UI");

                double maxW = Math.Max(10, logicalWidth - 6);
                double maxH = Math.Max(10, logicalHeight - 5);

                // Dynamically downscale font size step-by-step
                bool isMultiLine = item.text.Contains("\n") || item.text.Contains("\r") || item.text.Contains(" ");
                while (finalFontSize > 8)
                {
                    double h = MeasureTextHeight(item.text, finalFontSize, fontFamily, maxW);

                    if (isMultiLine)
                    {
                        if (h <= maxH)
                        {
                            break;
                        }
                    }
                    else
                    {
                        double w = MeasureTextWidth(item.text, finalFontSize, fontFamily);
                        if (w <= maxW && h <= maxH)
                        {
                            break;
                        }
                    }
                    finalFontSize -= 1.0;
                }

                // If element already exists, update properties
                Border border;
                if (_activeOverlays.TryGetValue(item.id, out border))
                {
                    Canvas.SetLeft(border, relativeX);
                    Canvas.SetTop(border, relativeY);
                    border.Width = logicalWidth;
                    border.Height = logicalHeight;
                    border.Background = bgBrush;

                    var textBlock = (OutlineTextBlock)border.Child;
                    textBlock.Text = item.text;
                    textBlock.FontSize = finalFontSize;
                    textBlock.Fill = textBrush;
                    textBlock.StrokeThickness = 0.0;
                }
                else
                {
                    // Create new OutlineTextBlock
                    var textBlock = new OutlineTextBlock
                    {
                        Text = item.text,
                        FontSize = finalFontSize,
                        Fill = textBrush,
                        Stroke = Brushes.Black,
                        StrokeThickness = 0.0,
                        FontFamily = fontFamily,
                        HorizontalAlignment = HorizontalAlignment.Center,
                        VerticalAlignment = VerticalAlignment.Center
                    };

                    // Wrap in Border to provide padding, rounded corners, and semi-transparent background
                    var newBorder = new Border
                    {
                        Background = bgBrush,
                        CornerRadius = new CornerRadius(5),
                        Padding = new Thickness(3, 2, 3, 2), // Slightly tighter padding for better overlay bounds fit
                        Child = textBlock,
                        Width = logicalWidth,
                        Height = logicalHeight
                    };

                    Canvas.SetLeft(newBorder, relativeX);
                    Canvas.SetTop(newBorder, relativeY);

                    // Add to canvas and map
                    OverlayCanvas.Children.Add(newBorder);
                    _activeOverlays[item.id] = newBorder;
                }
            }

            // Remove any overlays that are no longer active (Prune Ghost overlays instantly)
            var idsToRemove = new List<string>();
            foreach (var key in _activeOverlays.Keys)
            {
                if (!processedIds.Contains(key))
                {
                    idsToRemove.Add(key);
                }
            }

            foreach (var id in idsToRemove)
            {
                Border border;
                if (_activeOverlays.TryGetValue(id, out border))
                {
                    OverlayCanvas.Children.Remove(border);
                    _activeOverlays.Remove(id);
                }
            }
        }

        private void ClearAllOverlays()
        {
            OverlayCanvas.Children.Clear();
            _activeOverlays.Clear();
            
            // ClearAll時もステータスバーは生き残らせるためにCanvasへ再配置
            if (_statusBorder != null)
            {
                OverlayCanvas.Children.Add(_statusBorder);
            }
        }

        private void UpdateStatusUI(StatusUpdatePayload payload)
        {
            if (string.IsNullOrEmpty(payload.status))
            {
                _statusBorder.Visibility = Visibility.Collapsed;
                return;
            }

            _statusTextBlock.Text = payload.status;
            
            // PyQt and WPF logical coordinates are already DPI-scaled. 
            // Do not divide by _dpiScale to prevent double-scaling which pushes the border off-screen.
            double left = payload.x - SystemParameters.VirtualScreenLeft;
            double top = payload.y - SystemParameters.VirtualScreenTop;
            double w = payload.width;

            Canvas.SetLeft(_statusBorder, left);
            Canvas.SetTop(_statusBorder, top);
            _statusBorder.Width = w;
            _statusBorder.Visibility = Visibility.Visible;
        }
    }

    // --- JSON Serialization DTO Classes ---
    public class OverlayUpdatePayload
    {
        public List<OverlayItem> overlays { get; set; }
    }

    public class OverlayItem
    {
        public string id { get; set; }
        public string text { get; set; }
        public double x { get; set; }
        public double y { get; set; }
        public double width { get; set; }
        public double height { get; set; }
        public double font_size { get; set; }
        public string font_color { get; set; }
        public string bg_color { get; set; }
    }

    public class CaptureRequestPayload
    {
        public string window_title { get; set; }
        public string mode { get; set; }
        public int[] rect { get; set; }
    }

    public class StatusUpdatePayload
    {
        public string status { get; set; }
        public int x { get; set; }
        public int y { get; set; }
        public int width { get; set; }
    }
}
