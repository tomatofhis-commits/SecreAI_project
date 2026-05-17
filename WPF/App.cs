using System;
using System.Windows;

namespace RTtranslator_CS_Overlay
{
    public class App : Application
    {
        [STAThread]
        public static void Main()
        {
            var app = new App();
            app.Run(new MainWindow());
        }
    }
}
