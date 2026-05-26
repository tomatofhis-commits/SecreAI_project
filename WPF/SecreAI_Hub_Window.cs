using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Net;
using System.Net.Sockets;
using System.Net.Http;
using System.Threading.Tasks;
using System.Windows.Interop;

namespace SecreAI_Hub
{
    public class SecreAI_Hub_Window : Window
    {
        #region Win32 API for Window Enumeration & Safety
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder strText, int maxCount);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc enumProc, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

        [DllImport("user32.dll")]
        private static extern bool UnregisterHotKey(IntPtr hWnd, int id);
        #endregion

        // App States & Configuration
        private Dictionary<string, object> _configData;
        private Dictionary<string, object> _langData;
        private string _baseDir;
        private string _configPath;
        private string _activeSessionId;
        private string _currentAiStatus = "idle";
        private double _animationTime = 0.0;
        private Process _rttProcess;
        private Process _gameAiServerProcess;
        private System.Windows.Forms.NotifyIcon _trayIcon;
        private bool _isSettingsOpen = false;
        private bool _isWizardOpen = false;

        // UI Components
        private Border _indicatorBorder;
        private TextBox _logTextBox;
        private TextBox _chatTextBox;
        private ComboBox _winSelectorCombo;
        private ComboBox _voiceSpeedCombo;
        private TextBox _contextTextBox;
        private Label _logHeaderLabel;
        private Button _btnVoice;
        private Button _btnVision;
        private Button _btnStop;
        private Button _btnGood;
        private Button _btnBad;
        private Button _btnFix;
        private Button _btnClear;
        private Label _labelOps;
        private Label _labelDisplaySettings;
        private Label _labelTargetWindow;
        private Label _labelVoiceSpeed;
        private Label _labelContext;
        private Button _btnSave;
        private Button _btnAdvanced;
        private Button _btnThemeToggle;

        private SecreAI_Hub_Server _apiServer;
        private SecreAI_Hub_Overlay _currentOverlay;
        private MenuItem _ecoMenuItem;
        private MenuItem _singleMenuItem;
        private DispatcherTimer _animationTimer;

        public SecreAI_Hub_Window()
        {
            _baseDir = AppDomain.CurrentDomain.BaseDirectory;
            _configPath = Path.Combine(_baseDir, "data", "config.json");
            _activeSessionId = Guid.NewGuid().ToString();

            // Load Config & Language
            LoadConfig();
            LoadLanguage();

            // Window Settings
            Title = "SecreAI Hub v1.2.0 - Controller";
            Width = 1150;
            Height = 880;
            Background = new SolidColorBrush(Color.FromRgb(18, 18, 20));
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

            // Set Window Icon
            string iconPath = Path.Combine(_baseDir, "SecreAI.ico");
            if (File.Exists(iconPath))
            {
                try
                {
                    Icon = System.Windows.Media.Imaging.BitmapFrame.Create(new Uri(iconPath));
                }
                catch { }
            }

            // Setup Tray Icon
            SetupTrayIcon();

            // Build UI
            BuildUI();

            // Start Indicator Animation Timer
            _animationTimer = new DispatcherTimer(DispatcherPriority.Render);
            _animationTimer.Interval = TimeSpan.FromMilliseconds(50);
            _animationTimer.Tick += OnAnimationTick;
            _animationTimer.Start();

            // Start API Server on Port 5000
            _apiServer = new SecreAI_Hub_Server(this);
            _apiServer.Start();

            // Setup Setup Wizard or Auto Start VOICEVOX & RTT
            Loaded += (s, e) => {
                object geminiKey;
                _configData.TryGetValue("GEMINI_API_KEY", out geminiKey);
                if (geminiKey == null || string.IsNullOrEmpty(geminiKey.ToString()))
                {
                    OpenSetupWizard();
                }
                else
                {
                    AutoStartVoiceVoxAndRtt();
                }
                CheckForUpdates();
            };

            // Shut down hook
            Closing += OnWindowClosing;
        }

        #region Setup & Configuration Loading
        private void LoadConfig()
        {
            try
            {
                if (File.Exists(_configPath))
                {
                    string json = File.ReadAllText(_configPath);
                    var serializer = new JavaScriptSerializer();
                    _configData = serializer.Deserialize<Dictionary<string, object>>(json);
                }
            }
            catch { }

            if (_configData == null)
            {
                _configData = new Dictionary<string, object>();
            }
        }

        private void LoadLanguage()
        {
            string langCode = "ja";
            object langObj;
            if (_configData != null && _configData.TryGetValue("LANGUAGE", out langObj))
            {
                langCode = langObj.ToString();
            }

            string langPath = Path.Combine(_baseDir, "data", "lang", langCode + ".json");
            try
            {
                if (File.Exists(langPath))
                {
                    string langJson = File.ReadAllText(langPath);
                    var serializer = new JavaScriptSerializer();
                    _langData = serializer.Deserialize<Dictionary<string, object>>(langJson);
                }
            }
            catch { }

            if (_langData == null)
            {
                _langData = new Dictionary<string, object>();
            }
        }

        private string GetLangString(string section, string key, string defaultValue)
        {
            if (_langData != null && _langData.ContainsKey(section))
            {
                var sec = _langData[section] as Dictionary<string, object>;
                if (sec != null && sec.ContainsKey(key))
                {
                    return sec[key].ToString();
                }
            }
            return defaultValue;
        }
        #endregion

        #region Layout & Dynamic Design UI
        private void BuildUI()
        {
            Grid mainGrid = new Grid();
            mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star), MinWidth = 400 });
            mainGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(320), MaxWidth = 320 });

            // LEFT FRAME (Transcript & Log)
            Grid leftGrid = new Grid();
            leftGrid.Margin = new Thickness(10, 10, 5, 10);
            leftGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            leftGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            leftGrid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            leftGrid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            _logHeaderLabel = new Label
            {
                Content = "AI Transcript & System Log",
                Foreground = Brushes.White,
                FontSize = 16,
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 5)
            };
            leftGrid.Children.Add(_logHeaderLabel);
            Grid.SetRow(_logHeaderLabel, 0);

            // Neon state indicator
            _indicatorBorder = new Border
            {
                Height = 12,
                Background = new SolidColorBrush(Color.FromRgb(51, 51, 51)),
                CornerRadius = new CornerRadius(3),
                Margin = new Thickness(10, 2, 10, 8)
            };
            leftGrid.Children.Add(_indicatorBorder);
            Grid.SetRow(_indicatorBorder, 1);

            // Log Text Box
            _logTextBox = new TextBox
            {
                IsReadOnly = true,
                TextWrapping = TextWrapping.Wrap,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Background = new SolidColorBrush(Color.FromRgb(26, 26, 26)),
                Foreground = Brushes.White,
                FontSize = 13,
                FontFamily = new FontFamily("MS Gothic"),
                FontWeight = FontWeights.Bold,
                Margin = new Thickness(10, 0, 10, 5),
                BorderThickness = new Thickness(0),
                Padding = new Thickness(10)
            };
            leftGrid.Children.Add(_logTextBox);
            Grid.SetRow(_logTextBox, 2);

            // Chat input row
            Grid chatGrid = new Grid();
            chatGrid.Margin = new Thickness(10, 5, 10, 10);
            chatGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            chatGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            _chatTextBox = new TextBox
            {
                FontSize = 14,
                Height = 35,
                VerticalContentAlignment = VerticalAlignment.Center,
                Background = new SolidColorBrush(Color.FromRgb(40, 40, 40)),
                Foreground = Brushes.White,
                BorderBrush = new SolidColorBrush(Color.FromRgb(60, 60, 60)),
                Padding = new Thickness(5, 0, 5, 0)
            };
            _chatTextBox.KeyDown += (s, e) => {
                if (e.Key == Key.Enter) { SendChatMessage(); }
            };
            chatGrid.Children.Add(_chatTextBox);
            Grid.SetColumn(_chatTextBox, 0);

            Button btnSendChat = new Button
            {
                Content = "Send",
                Width = 80,
                Height = 35,
                Margin = new Thickness(5, 0, 0, 0),
                Background = new SolidColorBrush(Color.FromRgb(108, 92, 231)),
                Foreground = Brushes.White,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand
            };
            btnSendChat.Click += (s, e) => SendChatMessage();
            chatGrid.Children.Add(btnSendChat);
            Grid.SetColumn(btnSendChat, 1);

            leftGrid.Children.Add(chatGrid);
            Grid.SetRow(chatGrid, 3);

            mainGrid.Children.Add(leftGrid);
            Grid.SetColumn(leftGrid, 0);

            // RIGHT FRAME (Operations & settings)
            Border rightBorder = new Border
            {
                Background = new SolidColorBrush(Color.FromRgb(26, 26, 28)),
                Padding = new Thickness(15),
                Margin = new Thickness(5, 10, 10, 10),
                CornerRadius = new CornerRadius(5)
            };

            ScrollViewer rightScroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            };

            StackPanel rightPanel = new StackPanel();

            _labelOps = new Label
            {
                Content = "-- Operations --",
                Foreground = Brushes.LightGray,
                FontSize = 14,
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 0, 0, 10)
            };
            rightPanel.Children.Add(_labelOps);

            _btnVoice = CreateStyledButton("🎙 Voice Mode", "#6C5CE7", (s, e) => RunScript("game_ai.py", new[] { "voice" }));
            rightPanel.Children.Add(_btnVoice);

            _btnVision = CreateStyledButton("👁 Vision Mode", "#6C5CE7", (s, e) => RunScript("game_ai.py", new[] { "vision" }));
            rightPanel.Children.Add(_btnVision);

            _btnStop = CreateStyledButton("🛑 Stop AI", "#C0392B", (s, e) => StopAi());
            rightPanel.Children.Add(_btnStop);

            // Feedback panel
            Grid feedbackGrid = new Grid();
            feedbackGrid.Margin = new Thickness(0, 5, 0, 5);
            feedbackGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            feedbackGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            feedbackGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            _btnGood = CreateStyledButton("👍 Good", "#2ECC71", (s, e) => TriggerRemoteAction("feedback_good"), 2);
            _btnBad = CreateStyledButton("👎 Bad", "#E74C3C", (s, e) => TriggerRemoteAction("feedback_bad"), 2);
            _btnFix = CreateStyledButton("⚠ Fix", "#F39C12", (s, e) => TriggerRemoteAction("fix"), 2);

            feedbackGrid.Children.Add(_btnGood); Grid.SetColumn(_btnGood, 0);
            feedbackGrid.Children.Add(_btnBad); Grid.SetColumn(_btnBad, 1);
            feedbackGrid.Children.Add(_btnFix); Grid.SetColumn(_btnFix, 2);

            rightPanel.Children.Add(feedbackGrid);

            _btnClear = CreateStyledButton("🧹 Clear Log", "#7F8C8D", (s, e) => { _logTextBox.Clear(); });
            rightPanel.Children.Add(_btnClear);

            _labelDisplaySettings = new Label
            {
                Content = "-- Display Settings --",
                Foreground = Brushes.LightGray,
                FontSize = 14,
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, 15, 0, 5)
            };
            rightPanel.Children.Add(_labelDisplaySettings);

            _btnThemeToggle = CreateStyledButton("Toggle Theme", "#27AE60", (s, e) => ToggleLogTheme());
            rightPanel.Children.Add(_btnThemeToggle);

            _labelTargetWindow = CreateInputLabel("Target Window:");
            rightPanel.Children.Add(_labelTargetWindow);

            _winSelectorCombo = new ComboBox
            {
                Height = 30,
                Margin = new Thickness(0, 2, 0, 10)
            };
            RefreshWindowTitles();
            rightPanel.Children.Add(_winSelectorCombo);

            _labelVoiceSpeed = CreateInputLabel("Voice Speed:");
            rightPanel.Children.Add(_labelVoiceSpeed);

            _voiceSpeedCombo = new ComboBox
            {
                Height = 30,
                Margin = new Thickness(0, 2, 0, 10)
            };
            _voiceSpeedCombo.Items.Add("1.0");
            _voiceSpeedCombo.Items.Add("1.2");
            _voiceSpeedCombo.Items.Add("1.5");
            object speedVal;
            _configData.TryGetValue("VOICE_SPEED", out speedVal);
            _voiceSpeedCombo.SelectedItem = speedVal != null ? speedVal.ToString() : "1.2";
            rightPanel.Children.Add(_voiceSpeedCombo);

            _labelContext = CreateInputLabel("Context:");
            rightPanel.Children.Add(_labelContext);

            _contextTextBox = new TextBox
            {
                Height = 100,
                TextWrapping = TextWrapping.Wrap,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Background = new SolidColorBrush(Color.FromRgb(40, 40, 42)),
                Foreground = Brushes.White,
                BorderBrush = new SolidColorBrush(Color.FromRgb(60, 60, 60)),
                Padding = new Thickness(5),
                Margin = new Thickness(0, 2, 0, 10)
            };
            object contextVal;
            _configData.TryGetValue("TODAY_CONTEXT", out contextVal);
            _contextTextBox.Text = contextVal != null ? contextVal.ToString() : "";
            rightPanel.Children.Add(_contextTextBox);

            _btnSave = CreateStyledButton("Quick Save", "#3498DB", (s, e) => QuickSave());
            rightPanel.Children.Add(_btnSave);

            _btnAdvanced = CreateStyledButton("Advanced Settings", "#7F8C8D", (s, e) => OpenSettingsWindow());
            _btnAdvanced.Margin = new Thickness(0, 20, 0, 0);
            rightPanel.Children.Add(_btnAdvanced);

            rightScroll.Content = rightPanel;
            rightBorder.Child = rightScroll;

            mainGrid.Children.Add(rightBorder);
            Grid.SetColumn(rightBorder, 1);

            DockPanel rootDock = new DockPanel();
            
            // Create and add Top Menu
            Menu wpfMenu = CreateWpfMenuBar();
            DockPanel.SetDock(wpfMenu, Dock.Top);
            rootDock.Children.Add(wpfMenu);
            
            // Add Main Grid below it
            rootDock.Children.Add(mainGrid);
            
            Content = rootDock;

            // Apply translation strings
            UpdateUiText();
        }

        private Button CreateStyledButton(string text, string hexColor, RoutedEventHandler clickHandler, double sidePadding = 0)
        {
            var btn = new Button
            {
                Content = text,
                Height = 35,
                Margin = new Thickness(sidePadding, 5, sidePadding, 5),
                Background = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hexColor)),
                Foreground = Brushes.White,
                FontWeight = FontWeights.Bold,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand
            };
            btn.Click += clickHandler;
            return btn;
        }

        private Label CreateInputLabel(string content)
        {
            return new Label
            {
                Content = content,
                Foreground = Brushes.LightGray,
                FontSize = 12,
                Margin = new Thickness(0, 5, 0, 0)
            };
        }

        private void UpdateUiText()
        {
            _logHeaderLabel.Content = "AI Transcript & System Log";
            _labelOps.Content = GetLangString("gui", "op_operations", "-- Operations --");
            _btnVoice.Content = GetLangString("gui", "btn_voice_mode", "🎙 Voice Mode");
            _btnVision.Content = GetLangString("gui", "btn_vision_mode", "👁 Vision Mode");
            _btnStop.Content = GetLangString("gui", "btn_stop_ai", "🛑 Stop AI");
            _btnGood.Content = GetLangString("gui", "btn_good", "👍 Good");
            _btnBad.Content = GetLangString("gui", "btn_bad", "👎 Bad");
            _btnFix.Content = GetLangString("gui", "btn_fix", "⚠ Fix");
            _btnClear.Content = GetLangString("gui", "btn_clear_log", "🧹 Clear Log");
            _labelDisplaySettings.Content = GetLangString("gui", "op_display_settings", "-- Display Settings --");
            _btnThemeToggle.Content = GetLangString("gui", "btn_toggle_theme", "Toggle Theme");
            _labelTargetWindow.Content = GetLangString("gui", "label_target_window", "Target Window:");
            _labelVoiceSpeed.Content = GetLangString("gui", "label_voice_speed", "Voice Speed:");
            _labelContext.Content = GetLangString("gui", "label_context", "Context:");
            _btnSave.Content = GetLangString("gui", "btn_quick_save", "Quick Save");
            _btnAdvanced.Content = GetLangString("gui", "btn_open_settings", "Advanced Settings");

            // Reconstruct top menu bar dynamically when language changes
            DockPanel rootDock = Content as DockPanel;
            if (rootDock != null)
            {
                for (int i = 0; i < rootDock.Children.Count; i++)
                {
                    if (rootDock.Children[i] is Menu)
                    {
                        rootDock.Children.RemoveAt(i);
                        Menu newMenu = CreateWpfMenuBar();
                        DockPanel.SetDock(newMenu, Dock.Top);
                        rootDock.Children.Insert(i, newMenu);
                        break;
                    }
                }
            }
        }
        #endregion

        #region Neon State Indicator Animations
        private void OnAnimationTick(object sender, EventArgs e)
        {
            _animationTime += 0.05;

            if (_currentAiStatus == "listening")
            {
                // Cyan pulse
                byte val = (byte)(140 + 115 * Math.Abs(Math.Sin(_animationTime * 2)));
                _indicatorBorder.Background = new SolidColorBrush(Color.FromRgb(0, val, val));
            }
            else if (_currentAiStatus == "thinking")
            {
                // Sliding Purple Linear Gradient flow
                double offset = (_animationTime * 0.5) % 1.5 - 0.5;
                var brush = new LinearGradientBrush();
                brush.StartPoint = new Point(0, 0);
                brush.EndPoint = new Point(1, 0);
                brush.GradientStops.Add(new GradientStop(Color.FromRgb(30, 30, 30), 0.0));
                brush.GradientStops.Add(new GradientStop(Color.FromRgb(155, 89, 182), offset));
                brush.GradientStops.Add(new GradientStop(Color.FromRgb(155, 89, 182), offset + 0.3));
                brush.GradientStops.Add(new GradientStop(Color.FromRgb(30, 30, 30), 1.0));
                _indicatorBorder.Background = brush;
            }
            else if (_currentAiStatus == "speaking")
            {
                // Smooth gold-pink breathe fade
                double t = (Math.Sin(_animationTime * 1.5) + 1.0) / 2.0;
                byte r = (byte)(248 * (1.0 - t) + 247 * t);
                byte g = (byte)(165 * (1.0 - t) + 225 * t);
                byte b = (byte)(194 * (1.0 - t) + 173 * t);
                _indicatorBorder.Background = new SolidColorBrush(Color.FromRgb(r, g, b));
            }
            else
            {
                // Idle breathe
                byte val = (byte)(35 + 15 * Math.Abs(Math.Sin(_animationTime * 0.8)));
                _indicatorBorder.Background = new SolidColorBrush(Color.FromRgb(val, val, val));
            }
        }
        #endregion

        #region Operations, Settings & Launcher Logic
        public void UpdateLogArea(string text, bool isError = false, string errorCode = null)
        {
            if (!Dispatcher.CheckAccess())
            {
                Dispatcher.BeginInvoke(new Action(() => UpdateLogArea(text, isError, errorCode)));
                return;
            }

            string prefix = isError ? "[ERROR] " : "";
            _logTextBox.AppendText(prefix + text + "\n");
            _logTextBox.ScrollToEnd();

            if (isError)
            {
                string lowerText = text.ToLower();
                if (lowerText.Contains("api key expired") || lowerText.Contains("api_key_invalid") || (lowerText.Contains("api key") && (lowerText.Contains("invalid") || lowerText.Contains("expired"))))
                {
                    MessageBox.Show(
                        "【Gemini APIエラー】\n設定されているGemini APIキーの有効期限が切れているか、無効です。\n「Advanced Settings（詳細設定）」から有効なキーに更新してください。",
                        "APIキーのエラー検出",
                        MessageBoxButton.OK,
                        MessageBoxImage.Warning
                    );
                }
                else if (!string.IsNullOrEmpty(errorCode))
                {
                    MessageBox.Show("ErrorCode: " + errorCode + "\n" + text, "System Error Notify", MessageBoxButton.OK, MessageBoxImage.Error);
                }
            }
        }

        private void SendChatMessage()
        {
            string chatText = _chatTextBox.Text.Trim();
            if (!string.IsNullOrEmpty(chatText))
            {
                string youPrefix = GetLangString("system", "you_prefix", "You: ");
                UpdateLogArea(youPrefix + chatText);
                RunScript("game_ai.py", new[] { "chat", chatText });
                _chatTextBox.Clear();
            }
        }

        private string GetPythonExecutablePath()
        {
            string localPython = Path.Combine(_baseDir, "python_runtime", "python.exe");
            if (File.Exists(localPython))
            {
                return localPython;
            }
            return "python"; // Fallback to global python
        }

        private void RunScriptFallback(string scriptName, string[] args, bool isAiScript)
        {
            bool started = false;
            try
            {
                string scriptPath = Path.Combine(_baseDir, "scripts", scriptName);
                if (!File.Exists(scriptPath))
                {
                    scriptPath = Path.Combine(_baseDir, scriptName);
                }

                StringBuilder argBuilder = new StringBuilder();
                argBuilder.Append("\"" + scriptPath + "\"");
                foreach (var arg in args)
                {
                    argBuilder.Append(" \"" + arg + "\"");
                }

                ProcessStartInfo psi = new ProcessStartInfo(GetPythonExecutablePath(), argBuilder.ToString())
                {
                    WorkingDirectory = _baseDir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };

                Process p = Process.Start(psi);
                if (p != null)
                {
                    started = true;
                    
                    if (isAiScript)
                    {
                        Thread.Sleep(3000);
                        Dispatcher.BeginInvoke(new Action(() => {
                            _btnVoice.IsEnabled = true;
                            _btnVision.IsEnabled = true;
                        }));
                    }
                    
                    p.WaitForExit();
                }
            }
            catch (Exception ex)
            {
                Dispatcher.BeginInvoke(new Action(() => {
                    UpdateLogArea("Failed to run " + scriptName + " (Fallback): " + ex.Message, true);
                }));
            }
            finally
            {
                if (!started && isAiScript)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        _btnVoice.IsEnabled = true;
                        _btnVision.IsEnabled = true;
                    }));
                }
            }
        }

        private void RunScript(string scriptName, string[] args)
        {
            bool isAiScript = scriptName == "game_ai.py";
            bool isClearHistory = scriptName == "clear_history.py";
            bool isFixHistory = scriptName == "fix_history.py";
            bool isGiveFeedback = scriptName == "give_feedback.py";

            if (isAiScript)
            {
                bool isLocked = false;
                Dispatcher.Invoke(new Action(() => {
                    isLocked = !_btnVoice.IsEnabled;
                }));
                if (isLocked)
                {
                    return;
                }
            }

            _activeSessionId = Guid.NewGuid().ToString();

            Thread t = new Thread(() => {
                if (isAiScript)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        _btnVoice.IsEnabled = false;
                        _btnVision.IsEnabled = false;
                    }));
                }

                bool started = false;
                try
                {
                    LaunchGameAiServerProcess();

                    var serializer = new JavaScriptSerializer();

                    if (isAiScript)
                    {
                        var payload = new Dictionary<string, object>
                        {
                            { "mode", args.Length > 0 ? args[0] : "voice" },
                            { "chat_text", args.Length > 1 ? args[1] : "" },
                            { "session_id", _activeSessionId }
                        };
                        string json = serializer.Serialize(payload);

                        try
                        {
                            SendPostRequest("http://127.0.0.1:5003/api/execute", json);
                            started = true;
                        }
                        catch (Exception ex)
                        {
                            Dispatcher.BeginInvoke(new Action(() => {
                                UpdateLogArea("[Game AI] APIサーバーとの接続に失敗しました。再起動してリトライします: " + ex.Message, true);
                            }));
                            
                            RestartGameAiServerProcess();
                            
                            try
                            {
                                SendPostRequest("http://127.0.0.1:5003/api/execute", json);
                                started = true;
                            }
                            catch (Exception retryEx)
                            {
                                Dispatcher.BeginInvoke(new Action(() => {
                                    UpdateLogArea("[Game AI] リトライに失敗しました。従来のプロセス直接起動にフォールバックします: " + retryEx.Message, true);
                                }));
                            }
                        }

                        if (started)
                        {
                            Thread.Sleep(3000);
                            Dispatcher.BeginInvoke(new Action(() => {
                                _btnVoice.IsEnabled = true;
                                _btnVision.IsEnabled = true;
                            }));
                        }
                        else
                        {
                            RunScriptFallback(scriptName, args, isAiScript);
                        }
                    }
                    else if (isClearHistory || isFixHistory || isGiveFeedback)
                    {
                        string action = isClearHistory ? "clear" : (isFixHistory ? "fix" : "feedback");
                        var payload = new Dictionary<string, object>
                        {
                            { "action", action }
                        };
                        if (isGiveFeedback && args.Length > 0)
                        {
                            payload["feedback_type"] = args[0];
                        }
                        string json = serializer.Serialize(payload);

                        try
                        {
                            SendPostRequest("http://127.0.0.1:5003/api/action", json);
                            started = true;
                        }
                        catch
                        {
                            RunScriptFallback(scriptName, args, isAiScript);
                        }
                    }
                    else
                    {
                        RunScriptFallback(scriptName, args, isAiScript);
                    }
                }
                catch (Exception ex)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("Failed to run " + scriptName + ": " + ex.Message, true);
                    }));
                }
            });
            t.IsBackground = true;
            t.Start();
        }

        private void StopAi()
        {
            _activeSessionId = Guid.NewGuid().ToString();
            _currentAiStatus = "idle";
            string msg = GetLangString("system", "ai_stop_signal", "AI Stop Signal Sent.");
            UpdateLogArea(msg);

            ThreadPool.QueueUserWorkItem((state) => {
                try
                {
                    SendPostRequest("http://127.0.0.1:5003/api/stop", "");
                }
                catch { }
            });
        }

        public string GetActiveSessionId()
        {
            return _activeSessionId;
        }

        public void TriggerRemoteAction(string action)
        {
            if (action == "voice") RunScript("game_ai.py", new[] { "voice" });
            else if (action == "vision") RunScript("game_ai.py", new[] { "vision" });
            else if (action == "stop") StopAi();
            else if (action == "clear") RunScript("clear_history.py", new string[0]);
            else if (action == "fix") RunScript("fix_history.py", new string[0]);
            else if (action == "settings") OpenSettingsWindow();
            else if (action == "feedback_good") RunScript("give_feedback.py", new[] { "positive" });
            else if (action == "feedback_bad") RunScript("give_feedback.py", new[] { "negative" });
        }

        private void QuickSave()
        {
            _configData["TARGET_GAME_TITLE"] = _winSelectorCombo.SelectedItem != null ? _winSelectorCombo.SelectedItem.ToString() : "";
            
            double speed = 1.2;
            if (_voiceSpeedCombo.SelectedItem != null)
            {
                double.TryParse(_voiceSpeedCombo.SelectedItem.ToString(), out speed);
            }
            _configData["VOICE_SPEED"] = speed;
            _configData["TODAY_CONTEXT"] = _contextTextBox.Text.Trim();

            try
            {
                string json = new JavaScriptSerializer().Serialize(_configData);
                File.WriteAllText(_configPath, json);
                
                string saveSuccessMsg = GetLangString("system", "save_success", "Saved.");
                UpdateLogArea(saveSuccessMsg);

                // Sync to RTT if running
                SyncRttSettings();
            }
            catch (Exception ex)
            {
                UpdateLogArea("Quick Save failed: " + ex.Message, true);
            }
        }

        private Menu CreateWpfMenuBar()
        {
            Menu menuBar = new Menu
            {
                Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)), // Solid premium dark gray
                Foreground = Brushes.White,
                Padding = new Thickness(5, 0, 5, 0),
                Height = 30,
                VerticalContentAlignment = VerticalAlignment.Center,
                BorderThickness = new Thickness(0, 0, 0, 2),
                BorderBrush = new SolidColorBrush(Color.FromRgb(108, 92, 231)) // Sleek purple neon bottom line
            };

            // Helper to style main top-level menu items
            Action<MenuItem> styleTopLevelMenu = (mItem) =>
            {
                mItem.Foreground = Brushes.White;
                mItem.Background = Brushes.Transparent;
                mItem.Padding = new Thickness(12, 0, 12, 0);
                mItem.Height = 28;
                mItem.VerticalAlignment = VerticalAlignment.Center;
                mItem.VerticalContentAlignment = VerticalAlignment.Center;
                mItem.MouseEnter += (s, e) => { mItem.Background = new SolidColorBrush(Color.FromRgb(45, 45, 48)); };
                mItem.MouseLeave += (s, e) => { mItem.Background = Brushes.Transparent; };
            };

            // 1. System Cascade Menu
            MenuItem systemMenu = new MenuItem
            {
                Header = GetLangString("menu", "system_cascade", "システム (System)")
            };
            styleTopLevelMenu(systemMenu);
            menuBar.Items.Add(systemMenu);

            systemMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "refresh_windows", "ターゲットウィンドウ一覧を更新 (Refresh Windows)"), (s, e) => RefreshWindowTitles()));
            systemMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "open_memory", "記憶管理 (Memory Management)"), (s, e) => {
                Thread t = new Thread(() => {
                    try
                    {
                        string scriptPath = Path.Combine(_baseDir, "scripts", "run_memory_viewer.py");
                        ProcessStartInfo psi = new ProcessStartInfo(GetPythonExecutablePath(), "\"" + scriptPath + "\"")
                        {
                            WorkingDirectory = _baseDir,
                            CreateNoWindow = true,
                            UseShellExecute = false
                        };
                        Process.Start(psi);
                    }
                    catch (Exception ex)
                    {
                        Dispatcher.BeginInvoke(new Action(() => {
                            UpdateLogArea("Failed to launch Memory Viewer: " + ex.Message, true);
                        }));
                    }
                });
                t.IsBackground = true;
                t.Start();
            }));
            systemMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "reset_memory", "短期記憶の整理 (Reset Memory)"), (s, e) => {
                string confirmMsg = GetLangString("menu", "reset_memory_confirm_msg", "これまでの会話履歴（短期記憶）をリセットしますか？\n(Clear history?)");
                string confirmTitle = GetLangString("menu", "reset_memory_confirm_title", "確認 (Confirm)");
                if (MessageBox.Show(confirmMsg, confirmTitle, MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes)
                {
                    RunScript("clear_history.py", new string[0]);
                    UpdateLogArea(GetLangString("menu", "status_memory_reset", "短期記憶をリセットしました。"));
                }
            }));
            
            systemMenu.Items.Add(new Separator());
            systemMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "restart", "ハブの再起動 (Restart Hub)"), (s, e) => RestartHub()));
            systemMenu.Items.Add(new Separator());
            systemMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "exit", "終了 (Exit)"), (s, e) => ShutdownAllProcessesAndQuit()));

            // 2. RTトランスレーター Cascade Menu
            MenuItem rttMenu = new MenuItem
            {
                Header = GetLangString("menu", "rtt_cascade", "RTトランスレーター")
            };
            styleTopLevelMenu(rttMenu);
            menuBar.Items.Add(rttMenu);

            rttMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "rtt_start", "翻訳を開始 (Start)"), (s, e) => RttStart()));
            rttMenu.Items.Add(CreateMenuSubItem(GetLangString("menu", "rtt_stop", "翻訳を停止 (Stop)"), (s, e) => RttStop()));
            rttMenu.Items.Add(new Separator());

            _ecoMenuItem = new MenuItem
            {
                Header = GetLangString("menu", "rtt_eco_mode", "エコモード (Eco Mode)"),
                IsCheckable = true,
                IsChecked = IsEcoModeOn(),
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)),
                Padding = new Thickness(12, 6, 12, 6)
            };
            _ecoMenuItem.MouseEnter += (s, e) => { _ecoMenuItem.Background = new SolidColorBrush(Color.FromRgb(108, 92, 231)); };
            _ecoMenuItem.MouseLeave += (s, e) => { _ecoMenuItem.Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)); };
            _ecoMenuItem.Click += (s, e) => {
                ToggleRttEcoMode();
                _ecoMenuItem.IsChecked = IsEcoModeOn();
                _singleMenuItem.IsChecked = IsSingleModeOn();
            };
            rttMenu.Items.Add(_ecoMenuItem);

            _singleMenuItem = new MenuItem
            {
                Header = GetLangString("menu", "rtt_single_mode", "シングルモード (Single Mode)"),
                IsCheckable = true,
                IsChecked = IsSingleModeOn(),
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)),
                Padding = new Thickness(12, 6, 12, 6)
            };
            _singleMenuItem.MouseEnter += (s, e) => { _singleMenuItem.Background = new SolidColorBrush(Color.FromRgb(108, 92, 231)); };
            _singleMenuItem.MouseLeave += (s, e) => { _singleMenuItem.Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)); };
            _singleMenuItem.Click += (s, e) => {
                ToggleRttSingleMode();
                _singleMenuItem.IsChecked = IsSingleModeOn();
                _ecoMenuItem.IsChecked = IsEcoModeOn();
            };
            rttMenu.Items.Add(_singleMenuItem);

            // Sync menu checked states whenever the sub-menu opens
            rttMenu.SubmenuOpened += (s, e) => {
                _ecoMenuItem.IsChecked = IsEcoModeOn();
                _singleMenuItem.IsChecked = IsSingleModeOn();
            };

            return menuBar;
        }

        private MenuItem CreateMenuSubItem(string header, RoutedEventHandler onClick)
        {
            var item = new MenuItem
            {
                Header = header,
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)),
                Padding = new Thickness(12, 6, 12, 6),
                BorderThickness = new Thickness(0)
            };
            item.MouseEnter += (s, e) => { item.Background = new SolidColorBrush(Color.FromRgb(108, 92, 231)); };
            item.MouseLeave += (s, e) => { item.Background = new SolidColorBrush(Color.FromRgb(30, 30, 32)); };
            if (onClick != null)
            {
                item.Click += onClick;
            }
            return item;
        }

        private void OpenSettingsWindow()
        {
            lock (this)
            {
                if (_isSettingsOpen) return;
                _isSettingsOpen = true;
            }

            Thread t = new Thread(() => {
                try
                {
                    string scriptPath = Path.Combine(_baseDir, "scripts", "run_settings.py");
                    ProcessStartInfo psi = new ProcessStartInfo(GetPythonExecutablePath(), "\"" + scriptPath + "\"")
                    {
                        WorkingDirectory = _baseDir,
                        UseShellExecute = false,
                        CreateNoWindow = true
                    };
                    
                    var p = Process.Start(psi);
                    p.WaitForExit();

                    // Reload configurations and synchronize
                    Dispatcher.BeginInvoke(new Action(() => {
                        LoadConfig();
                        LoadLanguage();
                        UpdateUiText();
                        SyncRttSettings();
                        UpdateLogArea(GetLangString("log_messages", "settings_applied", "Settings applied."));
                    }));
                }
                catch (Exception ex)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("Failed to launch Settings UI: " + ex.Message, true);
                    }));
                }
                finally
                {
                    lock (this)
                    {
                        _isSettingsOpen = false;
                    }
                }
            });
            t.IsBackground = true;
            t.Start();
        }

        private void OpenSetupWizard()
        {
            lock (this)
            {
                if (_isWizardOpen) return;
                _isWizardOpen = true;
            }

            Thread t = new Thread(() => {
                try
                {
                    string scriptPath = Path.Combine(_baseDir, "scripts", "run_setup_wizard.py");
                    ProcessStartInfo psi = new ProcessStartInfo(GetPythonExecutablePath(), "\"" + scriptPath + "\"")
                    {
                        WorkingDirectory = _baseDir,
                        UseShellExecute = false,
                        CreateNoWindow = true
                    };
                    
                    var p = Process.Start(psi);
                    p.WaitForExit();

                    Dispatcher.BeginInvoke(new Action(() => {
                        LoadConfig();
                        LoadLanguage();
                        UpdateUiText();
                        AutoStartVoiceVoxAndRtt();
                    }));
                }
                catch (Exception ex)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("Failed to launch Setup Wizard: " + ex.Message, true);
                    }));
                }
                finally
                {
                    lock (this)
                    {
                        _isWizardOpen = false;
                    }
                }
            });
            t.IsBackground = true;
            t.Start();
        }
        #endregion

        #region Native Window Title Fetching
        private void RefreshWindowTitles()
        {
            _winSelectorCombo.Items.Clear();
            _winSelectorCombo.Items.Add("Default Window");

            List<string> titles = new List<string>();
            EnumWindows((hWnd, lParam) =>
            {
                if (IsWindowVisible(hWnd))
                {
                    StringBuilder sb = new StringBuilder(256);
                    GetWindowText(hWnd, sb, 256);
                    string title = sb.ToString().Trim();
                    if (!string.IsNullOrEmpty(title) && !titles.Contains(title))
                    {
                        titles.Add(title);
                    }
                }
                return true;
            }, IntPtr.Zero);

            titles.Sort();
            foreach (var t in titles)
            {
                _winSelectorCombo.Items.Add(t);
            }

            // Restore selection
            object targetTitle;
            _configData.TryGetValue("TARGET_GAME_TITLE", out targetTitle);
            if (targetTitle != null && _winSelectorCombo.Items.Contains(targetTitle.ToString()))
            {
                _winSelectorCombo.SelectedItem = targetTitle.ToString();
            }
            else
            {
                _winSelectorCombo.SelectedIndex = 0;
            }
        }
        #endregion

        #region Theme Toggle
        private void ToggleLogTheme()
        {
            // Soft slate or solid dark
            if (_logTextBox.Background.ToString() == "#FF1A1A1A")
            {
                _logTextBox.Background = new SolidColorBrush(Color.FromRgb(0, 255, 0)); // Pure green (G255) for OBS Chroma Key
                _logTextBox.Foreground = Brushes.White;
            }
            else
            {
                _logTextBox.Background = new SolidColorBrush(Color.FromRgb(26, 26, 26));
                _logTextBox.Foreground = Brushes.White;
            }
        }
        #endregion

        #region RTT Core Process & API Synchronization Controls
        public bool IsRttProcessRunning()
        {
            return _rttProcess != null && !_rttProcess.HasExited;
        }

        public void RttStart()
        {
            if (!IsRttProcessRunning())
            {
                // RTTコアが落ちている場合のみ起動してから待機ループを走らせる
                LaunchRttProcess();

                Thread waitThread = new Thread(() => {
                    for (int i = 0; i < 15; i++)
                    {
                        Thread.Sleep(1000);
                        try
                        {
                            if (PostConfigToRtt())
                            {
                                SendPostRequest("http://127.0.0.1:5001/api/start", "");
                                Dispatcher.BeginInvoke(new Action(() => {
                                    UpdateLogArea("[RTT] 翻訳を開始しました。");
                                }));
                                return;
                            }
                        }
                        catch { }
                    }
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("[RTT] 翻訳開始のタイムアウト。コアが応答しません。", true);
                    }));
                });
                waitThread.IsBackground = true;
                waitThread.Start();
            }
            else
            {
                // 既に起動中 → 即座に最新設定を同期してから翻訳開始を命令する
                Thread syncThread = new Thread(() => {
                    try
                    {
                        PostConfigToRtt();
                        SendPostRequest("http://127.0.0.1:5001/api/start", "");
                        Dispatcher.BeginInvoke(new Action(() => {
                            UpdateLogArea("[RTT] 翻訳を開始しました。");
                        }));
                    }
                    catch (Exception ex)
                    {
                        Dispatcher.BeginInvoke(new Action(() => {
                            UpdateLogArea("[RTT] 翻訳開始命令の送信に失敗しました: " + ex.Message, true);
                        }));
                    }
                });
                syncThread.IsBackground = true;
                syncThread.Start();
            }
        }

        public void RttStop()
        {
            Thread t = new Thread(() => {
                try
                {
                    SendPostRequest("http://127.0.0.1:5001/api/stop", "");
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("[RTT] 翻訳を停止しました。");
                    }));
                }
                catch (Exception ex)
                {
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("[RTT] 翻訳停止命令の送信に失敗しました: " + ex.Message, true);
                    }));
                }
            });
            t.IsBackground = true;
            t.Start();
        }

        public void ToggleRttEcoMode()
        {
            bool isEco = false;
            object ecoVal;
            if (_configData.TryGetValue("rtt_eco_mode", out ecoVal))
            {
                isEco = Convert.ToBoolean(ecoVal);
            }

            bool newEco = !isEco;
            _configData["rtt_eco_mode"] = newEco;

            // Exclusive with single mode
            if (newEco)
            {
                _configData["rtt_single_mode"] = false;
            }

            QuickSave();
        }

        public bool IsEcoModeOn()
        {
            object ecoVal;
            if (_configData.TryGetValue("rtt_eco_mode", out ecoVal))
            {
                return Convert.ToBoolean(ecoVal);
            }
            return false;
        }

        public void ToggleRttSingleMode()
        {
            bool isSingle = false;
            object singleVal;
            if (_configData.TryGetValue("rtt_single_mode", out singleVal))
            {
                isSingle = Convert.ToBoolean(singleVal);
            }

            bool newSingle = !isSingle;
            _configData["rtt_single_mode"] = newSingle;

            // Exclusive with eco mode
            if (newSingle)
            {
                _configData["rtt_eco_mode"] = false;
            }

            QuickSave();
        }

        public bool IsSingleModeOn()
        {
            object singleVal;
            if (_configData.TryGetValue("rtt_single_mode", out singleVal))
            {
                return Convert.ToBoolean(singleVal);
            }
            return false;
        }

        private void RestartHub()
        {
            try
            {
                if (_rttProcess != null && !_rttProcess.HasExited)
                {
                    try { _rttProcess.Kill(); } catch { }
                }
                
                string exePath = Process.GetCurrentProcess().MainModule.FileName;
                Process.Start(exePath);
                Environment.Exit(0);
            }
            catch (Exception ex)
            {
                UpdateLogArea("Failed to restart Hub: " + ex.Message, true);
            }
        }

        private void SyncRttSettings()
        {
            if (!IsRttProcessRunning()) return;

            Thread t = new Thread(() => {
                try
                {
                    if (PostConfigToRtt())
                    {
                        // Check if Ollama has a connection error
                        string statusJson = SendGetRequest("http://127.0.0.1:5001/api/status");
                        string ollamaErr = null;
                        if (!string.IsNullOrEmpty(statusJson))
                        {
                            try
                            {
                                var statusDict = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(statusJson);
                                object errObj;
                                if (statusDict != null && statusDict.TryGetValue("error", out errObj) && errObj != null)
                                {
                                    ollamaErr = errObj.ToString();
                                }
                            }
                            catch { }
                        }

                        Dispatcher.BeginInvoke(new Action(() => {
                            if (!string.IsNullOrEmpty(ollamaErr))
                            {
                                UpdateLogArea("[RTT] Ollama接続エラー発生中: " + ollamaErr, true);
                            }
                            else
                            {
                                UpdateLogArea("[RTT] 設定を同期しました。");
                            }
                        }));
                    }
                }
                catch { }
            });
            t.IsBackground = true;
            t.Start();
        }

        private bool PostConfigToRtt()
        {
            try
            {
                var rttCfg = BuildRttConfig();
                string json = new JavaScriptSerializer().Serialize(rttCfg);
                string response = SendPostRequest("http://127.0.0.1:5001/api/update_config", json);
                return !string.IsNullOrEmpty(response);
            }
            catch
            {
                return false;
            }
        }

        private Dictionary<string, object> BuildRttConfig()
        {
            var rttCfg = new Dictionary<string, object>
            {
                { "target_window_title", _configData.ContainsKey("TARGET_GAME_TITLE") ? _configData["TARGET_GAME_TITLE"] : "" },
                { "target_language", _configData.ContainsKey("rtt_target_language") ? _configData["rtt_target_language"] : "ja" },
                { "ollama_url", _configData.ContainsKey("OLLAMA_URL") ? _configData["OLLAMA_URL"] : "http://localhost:11434/v1" },
                { "ollama_model", _configData.ContainsKey("rtt_ollama_model") ? _configData["rtt_ollama_model"] : "translategemma:4b" },
                { "ocr_engine_mode", "dual_scout_hybrid" }
            };

            foreach (var kp in _configData)
            {
                if (kp.Key.StartsWith("rtt_"))
                {
                    string key = kp.Key.Substring(4).ToLower();
                    rttCfg[key] = kp.Value;
                }
            }

            // Force global OLLAMA_URL prioritizing
            if (_configData.ContainsKey("OLLAMA_URL"))
            {
                rttCfg["ollama_url"] = _configData["OLLAMA_URL"];
            }

            return rttCfg;
        }

        private void LaunchGameAiServerProcess()
        {
            if (_gameAiServerProcess != null && !_gameAiServerProcess.HasExited)
            {
                return;
            }

            try
            {
                if (_gameAiServerProcess != null)
                {
                    try { _gameAiServerProcess.Kill(); _gameAiServerProcess.WaitForExit(1000); } catch { }
                    _gameAiServerProcess = null;
                }

                string scriptPath = Path.Combine(_baseDir, "scripts", "game_ai.py");
                if (!File.Exists(scriptPath))
                {
                    scriptPath = Path.Combine(_baseDir, "game_ai.py");
                }

                StringBuilder argBuilder = new StringBuilder();
                argBuilder.Append("\"" + scriptPath + "\" server");

                ProcessStartInfo psi = new ProcessStartInfo(GetPythonExecutablePath(), argBuilder.ToString())
                {
                    WorkingDirectory = _baseDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardInput = true
                };

                _gameAiServerProcess = Process.Start(psi);
                Dispatcher.BeginInvoke(new Action(() => {
                    UpdateLogArea("[Game AI] 常駐 API サーバーを起動しました (ポート: 5003)。");
                }));
            }
            catch (Exception ex)
            {
                Dispatcher.BeginInvoke(new Action(() => {
                    UpdateLogArea("[Game AI] 常駐 API サーバーの起動に失敗しました: " + ex.Message, true);
                }));
            }
        }

        private void RestartGameAiServerProcess()
        {
            try
            {
                if (_gameAiServerProcess != null && !_gameAiServerProcess.HasExited)
                {
                    _gameAiServerProcess.Kill();
                    _gameAiServerProcess.WaitForExit(2000);
                }
            }
            catch { }
            _gameAiServerProcess = null;
            LaunchGameAiServerProcess();
            Thread.Sleep(2500);
        }

        private void LaunchRttProcess()
        {
            if (IsRttProcessRunning()) return;

            // RTT関連の既存ゾンビプロセスを事前にクリーンアップ
            try
            {
                foreach (var proc in Process.GetProcessesByName("RTtranslator_core"))
                {
                    try { proc.Kill(); proc.WaitForExit(1000); } catch { }
                }
                foreach (var proc in Process.GetProcessesByName("RTtranslator_CS_Overlay"))
                {
                    try { proc.Kill(); proc.WaitForExit(1000); } catch { }
                }
            }
            catch { }

            string rttExe = Path.Combine(_baseDir, "RTtranslator_core.exe");
            string rttScript = null;
            string rttScriptDir = null;

            if (!File.Exists(rttExe))
            {
                // Fallbacks to script directories
                string[] potentialDirs = {
                    Path.Combine(_baseDir, "RTtranslator"),
                    Path.Combine(Path.GetDirectoryName(_baseDir), "RTtranslator")
                };

                foreach (var d in potentialDirs)
                {
                    string p = Path.Combine(d, "main.py");
                    if (File.Exists(p))
                    {
                        rttScript = p;
                        rttScriptDir = d;
                        break;
                    }
                }
            }

            string rttConfigPath = Path.Combine(_baseDir, "data", "rtt_config.json");
            try
            {
                var rttCfg = BuildRttConfig();
                string json = new JavaScriptSerializer().Serialize(rttCfg);
                Directory.CreateDirectory(Path.GetDirectoryName(rttConfigPath));
                File.WriteAllText(rttConfigPath, json);
            }
            catch (Exception ex)
            {
                UpdateLogArea("[RTT] 設定ファイルの書き出しに失敗しました: " + ex.Message, true);
                return;
            }

            try
            {
                ProcessStartInfo psi;
                if (File.Exists(rttExe))
                {
                    psi = new ProcessStartInfo(rttExe, "--headless --config \"" + rttConfigPath + "\"")
                    {
                        WorkingDirectory = _baseDir,
                        CreateNoWindow = true,
                        UseShellExecute = false
                    };
                }
                else if (rttScript != null)
                {
                    UpdateLogArea("[RTT] EXEが見つかりません。Pythonスクリプトで代替起動します（開発モード）。");
                    psi = new ProcessStartInfo(GetPythonExecutablePath(), "\"" + rttScript + "\" --headless --config \"" + rttConfigPath + "\"")
                    {
                        WorkingDirectory = rttScriptDir,
                        CreateNoWindow = true,
                        UseShellExecute = false
                    };
                }
                else
                {
                    UpdateLogArea("[RTT] 実行ファイルおよび開発用スクリプトが見つかりませんでした。", true);
                    return;
                }

                _rttProcess = Process.Start(psi);
                UpdateLogArea("[RTT] コアプロセスを起動しました（待機中）。");

                // Start background thread to verify startup and sync settings
                Thread verifyThread = new Thread(() => {
                    for (int i = 0; i < 15; i++)
                    {
                        Thread.Sleep(1000);
                        try
                        {
                            string statusJson = SendGetRequest("http://127.0.0.1:5001/api/status");
                            if (!string.IsNullOrEmpty(statusJson))
                            {
                                // Sync latest settings
                                var rttCfg = BuildRttConfig();
                                string json = new JavaScriptSerializer().Serialize(rttCfg);
                                SendPostRequest("http://127.0.0.1:5001/api/update_config", json);

                                Dispatcher.BeginInvoke(new Action(() => {
                                    UpdateLogArea("[RTT] コアの起動と設定同期が完了しました。");
                                }));
                                return;
                            }
                        }
                        catch { }
                    }
                    Dispatcher.BeginInvoke(new Action(() => {
                        UpdateLogArea("[RTT] コアの起動確認がタイムアウトしました。", true);
                    }));
                });
                verifyThread.IsBackground = true;
                verifyThread.Start();
            }
            catch (Exception ex)
            {
                UpdateLogArea("[RTT] コアプロセスの起動に失敗しました: " + ex.Message, true);
            }
        }
        #endregion

        #region Helper background automatic processes launching
        private void AutoStartVoiceVoxAndRtt()
        {
            // Start RTT process headless
            LaunchRttProcess();

            // Start Game AI API server
            LaunchGameAiServerProcess();

            // Start VOICEVOX if path configured
            object vvPathObj;
            if (_configData.TryGetValue("VV_PATH", out vvPathObj) && vvPathObj != null)
            {
                string vvPath = vvPathObj.ToString();
                if (!string.IsNullOrEmpty(vvPath) && File.Exists(vvPath))
                {
                    ThreadPool.QueueUserWorkItem((state) => {
                        try
                        {
                            using (var socket = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp))
                            {
                                var result = socket.BeginConnect("127.0.0.1", 50021, null, null);
                                bool success = result.AsyncWaitHandle.WaitOne(1000, true);
                                if (!success)
                                {
                                    ProcessStartInfo vvPsi = new ProcessStartInfo(vvPath)
                                    {
                                        WorkingDirectory = Path.GetDirectoryName(vvPath),
                                        CreateNoWindow = true,
                                        UseShellExecute = false
                                    };
                                    Process.Start(vvPsi);
                                    Dispatcher.BeginInvoke(new Action(() => {
                                        UpdateLogArea("[VOICEVOX] 自動起動しました。");
                                    }));
                                }
                            }
                        }
                        catch { }
                    });
                }
            }
        }
        #endregion

        #region Avatar overlay displaying
        public void ShowOverlay(string text, string imagePath, double alphaVal, double displayTime, string status)
        {
            if (!string.IsNullOrEmpty(text))
            {
                text = text.Replace("#", "").Replace("＃", "");
            }
            _currentAiStatus = status;

            // Close existing overlay cleanly
            if (_currentOverlay != null)
            {
                try
                {
                    _currentOverlay.Close();
                }
                catch { }
                _currentOverlay = null;
            }

            // alphaVal=0 または status="idle" (= game_ai が "OFF" シグナルを送った) の場合は終了のみ
            if (alphaVal <= 0.0 || string.Equals(status, "idle", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            try
            {
                _currentOverlay = new SecreAI_Hub_Overlay(text, imagePath, alphaVal, displayTime);
                _currentOverlay.Show();
            }
            catch (Exception ex)
            {
                UpdateLogArea("Overlay trigger error: " + ex.Message, true);
            }
        }
        #endregion

        #region System Tray Integration
        private void SetupTrayIcon()
        {
            try
            {
                _trayIcon = new System.Windows.Forms.NotifyIcon();
                _trayIcon.Text = "SecreAI Hub";
                
                // Load embedded icon from base directory if exists
                string iconPath = Path.Combine(_baseDir, "SecreAI.ico");
                if (File.Exists(iconPath))
                {
                    _trayIcon.Icon = new System.Drawing.Icon(iconPath);
                }
                else
                {
                    _trayIcon.Icon = System.Drawing.SystemIcons.Application;
                }

                _trayIcon.DoubleClick += (s, e) => {
                    Show();
                    WindowState = WindowState.Normal;
                };

                var contextMenu = new System.Windows.Forms.ContextMenu();
                contextMenu.MenuItems.Add("表示 (Show)", (s, e) => {
                    Show();
                    WindowState = WindowState.Normal;
                });
                contextMenu.MenuItems.Add("終了 (Exit)", (s, e) => {
                    ShutdownAllProcessesAndQuit();
                });

                _trayIcon.ContextMenu = contextMenu;
                _trayIcon.Visible = true;
            }
            catch { }

            StateChanged += (s, e) => {
                if (WindowState == WindowState.Minimized)
                {
                    Hide();
                }
            };
        }
        #endregion

        #region Global Hotkeys & GitHub Update Checker
        private const int HOTKEY_VOICE_ID = 9001;
        private const int HOTKEY_VISION_ID = 9002;
        private const int HOTKEY_STOP_ID = 9003;

        protected override void OnSourceInitialized(EventArgs e)
        {
            base.OnSourceInitialized(e);
            try
            {
                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                HwndSource source = HwndSource.FromHwnd(hwnd);
                if (source != null)
                {
                    source.AddHook(HwndHook);
                }
                RegisterGlobalHotkeys();
            }
            catch (Exception ex)
            {
                UpdateLogArea("Failed to initialize global hotkeys: " + ex.Message, true);
            }
        }

        private IntPtr HwndHook(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
        {
            const int WM_HOTKEY = 0x0312;
            if (msg == WM_HOTKEY)
            {
                int id = wParam.ToInt32();
                if (id == HOTKEY_VOICE_ID)
                {
                    if (_btnVoice.IsEnabled)
                    {
                        RunScript("game_ai.py", new string[] { "voice" });
                    }
                    handled = true;
                }
                else if (id == HOTKEY_VISION_ID)
                {
                    if (_btnVision.IsEnabled)
                    {
                        RunScript("game_ai.py", new string[] { "vision" });
                    }
                    handled = true;
                }
                else if (id == HOTKEY_STOP_ID)
                {
                    StopAi();
                    handled = true;
                }
            }
            return IntPtr.Zero;
        }

        private void RegisterGlobalHotkeys()
        {
            try
            {
                string voiceKey = "ctrl+alt+v";
                string visionKey = "ctrl+alt+s";
                string stopKey = "ctrl+alt+x";

                object hotkeysObj;
                if (_configData.TryGetValue("HOTKEYS", out hotkeysObj) && hotkeysObj is Dictionary<string, object>)
                {
                    Dictionary<string, object> hkDict = (Dictionary<string, object>)hotkeysObj;
                    object vVal;
                    if (hkDict.TryGetValue("voice_mode", out vVal)) voiceKey = vVal.ToString();
                    object viVal;
                    if (hkDict.TryGetValue("vision_mode", out viVal)) visionKey = viVal.ToString();
                    object sVal;
                    if (hkDict.TryGetValue("stop_ai", out sVal)) stopKey = sVal.ToString();
                }

                IntPtr hwnd = new WindowInteropHelper(this).Handle;
                
                UnregisterHotKey(hwnd, HOTKEY_VOICE_ID);
                UnregisterHotKey(hwnd, HOTKEY_VISION_ID);
                UnregisterHotKey(hwnd, HOTKEY_STOP_ID);

                RegisterSingleHotkey(hwnd, HOTKEY_VOICE_ID, voiceKey);
                RegisterSingleHotkey(hwnd, HOTKEY_VISION_ID, visionKey);
                RegisterSingleHotkey(hwnd, HOTKEY_STOP_ID, stopKey);
            }
            catch (Exception ex)
            {
                UpdateLogArea("Hotkey registration error: " + ex.Message, true);
            }
        }

        private void RegisterSingleHotkey(IntPtr hwnd, int id, string keyStr)
        {
            if (string.IsNullOrEmpty(keyStr)) return;
            
            uint modifiers = 0;
            uint vk = 0;

            string[] parts = keyStr.ToLower().Split('+');
            foreach (var part in parts)
            {
                string p = part.Trim();
                if (p == "ctrl" || p == "control") modifiers |= 0x0002;
                else if (p == "alt") modifiers |= 0x0001;
                else if (p == "shift") modifiers |= 0x0004;
                else if (p == "win") modifiers |= 0x0008;
                else if (p.Length == 1)
                {
                    vk = (uint)p.ToUpper()[0];
                }
            }

            if (vk != 0)
            {
                RegisterHotKey(hwnd, id, modifiers, vk);
            }
        }

        private async void CheckForUpdates()
        {
            await Task.Delay(3000); // Wait 3 seconds
            try
            {
                using (var client = new HttpClient())
                {
                    client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (compatible; SecreAI-Hub-UpdateChecker/1.1)");
                    client.Timeout = TimeSpan.FromSeconds(10);
                    
                    var response = await client.GetAsync("https://api.github.com/repos/tomatofhis/SecreAI_project/releases/latest");
                    if (response.IsSuccessStatusCode)
                    {
                        var json = await response.Content.ReadAsStringAsync();
                        var serializer = new JavaScriptSerializer();
                        var data = serializer.Deserialize<Dictionary<string, object>>(json);
                        
                        object tagObj;
                        if (data != null && data.TryGetValue("tag_name", out tagObj))
                        {
                            string latestV = tagObj.ToString().TrimStart('v');
                            string currentV = "1.2.0";
                            
                            if (string.Compare(latestV, currentV) > 0)
                            {
                                object urlObj;
                                string htmlUrl = data.TryGetValue("html_url", out urlObj) ? urlObj.ToString() : "";
                                string msg = "【UPDATE】最新バージョン v" + latestV + " が利用可能です！\n詳細はGitHubを確認してください: " + htmlUrl;
                                UpdateLogArea(msg);
                            }
                        }
                    }
                }
            }
            catch { }
        }
        #endregion

        #region Clean shutdown
        private void OnWindowClosing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            // Instead of closing, minimize to system tray cleanly if user clicks close
            e.Cancel = true;
            Hide();

            // Show balloon tip to notify user about background operation
            try
            {
                if (_trayIcon != null)
                {
                    _trayIcon.ShowBalloonTip(
                        3000,
                        "SecreAI Hub",
                        "ハブはバックグラウンドで動作し続けます。完全に終了するには、通知領域（タスクバー右下）のアイコンを右クリックして「終了 (Exit)」を選択してください。",
                        System.Windows.Forms.ToolTipIcon.Info
                    );
                }
            }
            catch { }
        }

        private void ShutdownAllProcessesAndQuit()
        {
            try
            {
                try
                {
                    IntPtr hwnd = new WindowInteropHelper(this).Handle;
                    UnregisterHotKey(hwnd, HOTKEY_VOICE_ID);
                    UnregisterHotKey(hwnd, HOTKEY_VISION_ID);
                    UnregisterHotKey(hwnd, HOTKEY_STOP_ID);
                }
                catch { }

                // Invalidate API Server
                if (_apiServer != null)
                {
                    _apiServer.Stop();
                }

                // Stop active overlays
                if (_currentOverlay != null)
                {
                    _currentOverlay.Close();
                }

                // Kill RTT processes
                if (_rttProcess != null && !_rttProcess.HasExited)
                {
                    try
                    {
                        SendPostRequest("http://127.0.0.1:5001/api/stop", "");
                    }
                    catch { }
                    try
                    {
                        _rttProcess.Kill();
                    }
                    catch { }
                }

                // Kill Game AI server process
                if (_gameAiServerProcess != null && !_gameAiServerProcess.HasExited)
                {
                    try
                    {
                        SendPostRequest("http://127.0.0.1:5003/api/stop", "");
                    }
                    catch { }
                    try
                    {
                        _gameAiServerProcess.Kill();
                    }
                    catch { }
                }

                // Strictly kill any remaining RTtranslator processes by name
                try
                {
                    foreach (var proc in Process.GetProcessesByName("RTtranslator_core"))
                    {
                        try { proc.Kill(); } catch { }
                    }
                    foreach (var proc in Process.GetProcessesByName("RTtranslator_CS_Overlay"))
                    {
                        try { proc.Kill(); } catch { }
                    }
                }
                catch { }

                if (_trayIcon != null)
                {
                    _trayIcon.Dispose();
                }

                // Strictly shutdown self and all child process tree using taskkill
                Process.Start(new ProcessStartInfo("taskkill", "/F /PID " + Process.GetCurrentProcess().Id + " /T")
                {
                    CreateNoWindow = true,
                    UseShellExecute = false
                });
            }
            catch
            {
                Environment.Exit(0);
            }
        }
        #endregion

        #region HTTP Requests Helpers
        private string SendPostRequest(string url, string postData)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.Timeout = 1500;
            request.ContentType = "application/json";
            byte[] byteArray = Encoding.UTF8.GetBytes(postData);
            request.ContentLength = byteArray.Length;
            using (Stream dataStream = request.GetRequestStream())
            {
                dataStream.Write(byteArray, 0, byteArray.Length);
            }
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            {
                return reader.ReadToEnd();
            }
        }

        private string SendGetRequest(string url)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
                request.Method = "GET";
                request.Timeout = 1500;
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                {
                    return reader.ReadToEnd();
                }
            }
            catch
            {
                return null;
            }
        }
        #endregion
    }
}
