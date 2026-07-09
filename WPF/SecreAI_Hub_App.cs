using System;
using System.IO;
using System.Threading;
using System.Windows;
using System.Web.Script.Serialization;
using System.Collections.Generic;

namespace SecreAI_Hub
{
    public class App : Application
    {
        private static Mutex _mutex;
        private const string MutexName = "Global\\SecreAI_Hub_WPF_Mutex_ID_98765";

        [STAThread]
        public static void Main()
        {
            // 1. Single Instance Check based on installation path
            string baseDir = AppDomain.CurrentDomain.BaseDirectory.ToLower().TrimEnd('\\');
            string uniqueMutexName = MutexName + "_" + baseDir.GetHashCode().ToString("X");
            bool createdNew;
            _mutex = new Mutex(true, uniqueMutexName, out createdNew);

            if (!createdNew)
            {
                ShowSingleInstanceWarning();
                return;
            }

            // 2. Launch Application
            var app = new App();
            app.Run(new SecreAI_Hub_Window());
        }

        private static void ShowSingleInstanceWarning()
        {
            // Attempt to load language settings to localize the warning message
            string title = "二重起動";
            string message = "SecreAI Hub は既に起動しています。";
            
            try
            {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string configPath = Path.Combine(baseDir, "data", "config.json");
                string langCode = "ja";

                if (File.Exists(configPath))
                {
                    string json = File.ReadAllText(configPath);
                    var serializer = new JavaScriptSerializer();
                    var config = serializer.Deserialize<Dictionary<string, object>>(json);
                    if (config != null && config.ContainsKey("LANGUAGE"))
                    {
                        langCode = config["LANGUAGE"].ToString();
                    }
                }

                string langPath = Path.Combine(baseDir, "data", "lang", langCode + ".json");
                if (File.Exists(langPath))
                {
                    string langJson = File.ReadAllText(langPath);
                    var serializer = new JavaScriptSerializer();
                    var langData = serializer.Deserialize<Dictionary<string, object>>(langJson);
                    if (langData != null && langData.ContainsKey("system"))
                    {
                        var systemSection = langData["system"] as Dictionary<string, object>;
                        if (systemSection != null)
                        {
                            if (systemSection.ContainsKey("single_instance_title"))
                                title = systemSection["single_instance_title"].ToString();
                            if (systemSection.ContainsKey("single_instance_msg"))
                                message = systemSection["single_instance_msg"].ToString();
                        }
                    }
                }
            }
            catch
            {
                // Fallback to Japanese defaults
            }

            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        }
    }
}
