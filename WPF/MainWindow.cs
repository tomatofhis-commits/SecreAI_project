using System;
using System.Collections.Generic;
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

        private const int GWL_EXSTYLE = -20;
        private const int WS_EX_TRANSPARENT = 0x00000020;
        private const int WS_EX_NOACTIVATE = 0x08000000;

        // --- UI Canvas ---
        public Canvas OverlayCanvas { get; private set; }

        // --- HTTP API Listener ---
        private HttpListener _httpListener;
        private Thread _listenerThread;
        private bool _isRunning = false;

        // --- Overlay Tracking Dictionary ---
        private readonly Dictionary<string, Border> _activeOverlays = new Dictionary<string, Border>();

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

            this.Loaded += Window_Loaded;
            this.Closed += Window_Closed;
        }

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);

            // Hook window styles via Win32 to make it click-through and non-activatable (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            var hwnd = new WindowInteropHelper(this).Handle;
            int extendedStyle = GetWindowLong(hwnd, GWL_EXSTYLE);
            SetWindowLong(hwnd, GWL_EXSTYLE, extendedStyle | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE);
        }

        private void Window_Loaded(object sender, RoutedEventArgs e)
        {
            // Start local HTTP Server on background thread
            StartHttpServer();
        }

        private void Window_Closed(object sender, EventArgs e)
        {
            StopHttpServer();
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
                MessageBox.Show($"Failed to start local C# API server on port 5002:\n{ex.Message}", "RTT Overlay Error", MessageBoxButton.OK, MessageBoxImage.Error);
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
                            Dispatcher.Invoke(() => SyncOverlays(payload.overlays));
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
                    Dispatcher.Invoke(() => ClearAllOverlays());
                    SendJsonResponse(resp, new { status = "ok" });
                }
                else if (path == "/api/stop" && req.HttpMethod == "POST")
                {
                    SendJsonResponse(resp, new { status = "ok", message = "Stopping application" });
                    Dispatcher.Invoke(() => this.Close());
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

                // Align coordinates relative to our full-screen Canvas positioned at (vLeft, vTop)
                double relativeX = item.x - vLeft;
                double relativeY = item.y - vTop;

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

                // If element already exists, update properties
                if (_activeOverlays.TryGetValue(item.id, out Border border))
                {
                    Canvas.SetLeft(border, relativeX);
                    Canvas.SetTop(border, relativeY);
                    border.Width = item.width;
                    border.Height = item.height;
                    border.Background = bgBrush;

                    var textBlock = (OutlineTextBlock)border.Child;
                    textBlock.Text = item.text;
                    textBlock.FontSize = item.font_size > 0 ? item.font_size : 14;
                    textBlock.Fill = textBrush;
                }
                else
                {
                    // Create new OutlineTextBlock
                    var textBlock = new OutlineTextBlock
                    {
                        Text = item.text,
                        FontSize = item.font_size > 0 ? item.font_size : 14,
                        Fill = textBrush,
                        Stroke = Brushes.Black,
                        StrokeThickness = 2.5,
                        FontFamily = new FontFamily("MS Gothic"),
                        HorizontalAlignment = HorizontalAlignment.Center,
                        VerticalAlignment = VerticalAlignment.Center
                    };

                    // Wrap in Border to provide padding, rounded corners, and semi-transparent background
                    var newBorder = new Border
                    {
                        Background = bgBrush,
                        CornerRadius = new CornerRadius(5),
                        Padding = new Thickness(6, 4, 6, 4),
                        Child = textBlock,
                        Width = item.width,
                        Height = item.height
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
                if (_activeOverlays.TryGetValue(id, out Border border))
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
}
