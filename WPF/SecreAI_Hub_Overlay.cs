using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace SecreAI_Hub
{
    public class SecreAI_Hub_Overlay : Window
    {
        #region Win32 API Imports
        [DllImport("user32.dll", SetLastError = true)]
        private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

        [DllImport("user32.dll")]
        private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

        [DllImport("user32.dll")]
        private static extern bool SetWindowDisplayAffinity(IntPtr hwnd, uint affinity);

        [DllImport("user32.dll")]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        private const int GWL_EXSTYLE = -20;
        private const int WS_EX_TRANSPARENT = 0x00000020;
        private const int WS_EX_LAYERED = 0x00080000;
        private const int WS_EX_NOACTIVATE = 0x08000000;
        private const int WS_EX_TOOLWINDOW = 0x00000080;
        private const int WS_EX_TOPMOST = 0x00000008;

        private const uint WDA_EXCLUDEFROMCAPTURE = 0x00000011;
        private static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
        private const uint SWP_NOMOVE = 0x0002;
        private const uint SWP_NOSIZE = 0x0001;
        private const uint SWP_NOACTIVATE = 0x0010;
        private const uint SWP_SHOWWINDOW = 0x0040;
        #endregion

        private DispatcherTimer _closeTimer;

        public SecreAI_Hub_Overlay(string text, string imagePath, double alphaVal, double displayTimeSeconds)
        {
            // 1. Basic Window Setup
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = Brushes.Transparent;
            Topmost = true;
            ShowInTaskbar = false;
            Title = "SecreAI Avatar Voice Overlay";

            // 2. Position Window: Display size 100% height, floating on the right side
            double targetWidth = 380;
            Width = targetWidth;
            Height = SystemParameters.WorkArea.Height - 40; // 100% height of work area minus margins
            SizeToContent = SizeToContent.Manual; // Use fixed height to allow dynamic font calculation

            Left = SystemParameters.WorkArea.Width - targetWidth - 20;
            Top = SystemParameters.WorkArea.Top + 20;

            // Set universal opacity for the entire window (Text, Image, Border, and Background)
            Opacity = alphaVal;

            // 3. Create dark panel layout with elegant corner radius and purple accent neon border
            var border = new Border
            {
                Background = new SolidColorBrush(Color.FromRgb(20, 20, 24)), // Alpha is now handled by Window.Opacity
                BorderBrush = new SolidColorBrush(Color.FromRgb(108, 92, 231)), // Purple premium neon border
                BorderThickness = new Thickness(2),
                Padding = new Thickness(18),
                CornerRadius = new CornerRadius(15) // Elegant rounded corners
            };

            var grid = new Grid();
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            // 4. Load Avatar Image if exists
            if (!string.IsNullOrEmpty(imagePath) && File.Exists(imagePath))
            {
                try
                {
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.UriSource = new Uri(imagePath);
                    bitmap.CreateOptions = BitmapCreateOptions.IgnoreImageCache;
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.EndInit();

                    var imageControl = new Image
                    {
                        Source = bitmap,
                        MaxWidth = 340,
                        MaxHeight = 220, // Slightly reduced to give text more luxurious vertical breathing room
                        Margin = new Thickness(0, 0, 0, 15),
                        HorizontalAlignment = HorizontalAlignment.Center,
                        Stretch = Stretch.Uniform
                    };
                    Grid.SetRow(imageControl, 0);
                    grid.Children.Add(imageControl);
                }
                catch { }
            }

            // 5. Add Text message (FontSize will be dynamically adjusted on Window Loaded)
            var textBlock = new TextBlock
            {
                Text = text,
                Foreground = Brushes.White,
                FontSize = 16.0,
                FontWeight = FontWeights.Bold,
                FontFamily = new FontFamily("Meiryo, Microsoft YaHei, Segoe UI"),
                TextWrapping = TextWrapping.Wrap,
                TextAlignment = TextAlignment.Left,
                HorizontalAlignment = HorizontalAlignment.Left,
                MaxWidth = 340,
                Margin = new Thickness(5, 2, 5, 2)
            };

            var scrollViewer = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Content = textBlock
            };
            Grid.SetRow(scrollViewer, 1);
            grid.Children.Add(scrollViewer);

            border.Child = grid;
            Content = border;

            // 6. Setup Close Timer
            _closeTimer = new DispatcherTimer();
            _closeTimer.Interval = TimeSpan.FromSeconds(displayTimeSeconds);
            _closeTimer.Tick += (s, e) =>
            {
                _closeTimer.Stop();
                Close();
            };

            Loaded += OnWindowLoaded;
        }

        private void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            // Precision alignment: Position the floating panel on the right side
            double targetWidth = 380;
            Left = SystemParameters.WorkArea.Width - targetWidth - 20;
            Top = SystemParameters.WorkArea.Top + 20;

            // Apply click-through, toolwindow, no-activate Win32 styling
            IntPtr hwnd = new WindowInteropHelper(this).Handle;
            
            // 1. Capture exclusion setting
            SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE);

            // 2. Click-through and non-focusable flags
            int exStyle = GetWindowLong(hwnd, GWL_EXSTYLE);
            int newStyle = exStyle | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST;
            SetWindowLong(hwnd, GWL_EXSTYLE, newStyle);

            // 3. Ensure topmost position
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);

            // Dynamic Font Size adjustment
            var border = Content as Border;
            if (border != null)
            {
                var grid = border.Child as Grid;
                if (grid != null)
                {
                    ScrollViewer scrollViewer = null;
                    TextBlock textBlock = null;
                    foreach (var child in grid.Children)
                    {
                        if (child is ScrollViewer)
                        {
                            scrollViewer = child as ScrollViewer;
                            textBlock = scrollViewer.Content as TextBlock;
                        }
                    }
                    if (scrollViewer != null && textBlock != null)
                    {
                        AdjustFontSizeToFit(textBlock, scrollViewer, grid);
                    }
                }
            }

            // Start timer
            _closeTimer.Start();
        }

        private void AdjustFontSizeToFit(TextBlock textBlock, ScrollViewer scrollViewer, Grid parentGrid)
        {
            parentGrid.UpdateLayout();
            double availableHeight = scrollViewer.ActualHeight;
            if (availableHeight <= 0)
            {
                // Fallback sizing estimation
                bool hasImage = parentGrid.Children.Count > 1;
                double approxImageHeight = hasImage ? 235 : 0;
                availableHeight = this.Height - approxImageHeight - 50; 
            }

            double fontSize = 16.0;
            double minFontSize = 9.0; // Allow shrinking to 9px for extremely long text
            textBlock.FontSize = fontSize;
            
            while (fontSize > minFontSize)
            {
                textBlock.Measure(new Size(textBlock.MaxWidth, double.PositiveInfinity));
                if (textBlock.DesiredSize.Height <= availableHeight)
                {
                    break;
                }
                fontSize -= 0.5; // Fine-tune size
                textBlock.FontSize = fontSize;
            }
        }
    }
}
