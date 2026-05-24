using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Windows;

namespace SecreAI_Hub
{
    public class SecreAI_Hub_Server
    {
        private readonly HttpListener _listener;
        private readonly SecreAI_Hub_Window _window;
        private Thread _serverThread;
        private bool _isRunning;

        public SecreAI_Hub_Server(SecreAI_Hub_Window window)
        {
            _window = window;
            _listener = new HttpListener();
            // Prefix to listen to all requests on port 5000 for localhost
            _listener.Prefixes.Add("http://localhost:5000/");
            _listener.Prefixes.Add("http://127.0.0.1:5000/");
        }

        public void Start()
        {
            _isRunning = true;
            _serverThread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "SecreAI_Hub_API_Server"
            };
            _serverThread.Start();
        }

        public void Stop()
        {
            _isRunning = false;
            try
            {
                if (_listener.IsListening)
                {
                    _listener.Stop();
                    _listener.Close();
                }
            }
            catch { }
        }

        private void ListenLoop()
        {
            try
            {
                _listener.Start();
                _window.UpdateLogArea("Hub API Server started on port 5000.");
            }
            catch (Exception ex)
            {
                _window.UpdateLogArea("Failed to start API Server: " + ex.Message, true);
                return;
            }

            while (_isRunning)
            {
                try
                {
                    HttpListenerContext context = _listener.GetContext();
                    ThreadPool.QueueUserWorkItem((state) => HandleRequest((HttpListenerContext)state), context);
                }
                catch (HttpListenerException)
                {
                    // Listener stopped or interrupted
                    break;
                }
                catch (Exception ex)
                {
                    _window.UpdateLogArea("API Server loop error: " + ex.Message, true);
                }
            }
        }

        private void HandleRequest(HttpListenerContext context)
        {
            HttpListenerRequest request = context.Request;
            HttpListenerResponse response = context.Response;

            // Enable CORS for StreamDeck or other local dashboards
            response.Headers.Add("Access-Control-Allow-Origin", "*");
            response.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            response.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

            if (request.HttpMethod == "OPTIONS")
            {
                response.StatusCode = (int)HttpStatusCode.OK;
                response.Close();
                return;
            }

            string path = request.Url.AbsolutePath.ToLower();
            string responseString = "";
            int statusCode = (int)HttpStatusCode.OK;

            try
            {
                if (path == "/api/log" && request.HttpMethod == "POST")
                {
                    string body = ReadRequestBody(request);
                    var data = DeserializeJson(body);
                    string msg = data.ContainsKey("message") ? data["message"].ToString() : "";
                    bool isError = data.ContainsKey("is_error") && Convert.ToBoolean(data["is_error"]);
                    string errorCode = data.ContainsKey("error_code") && data["error_code"] != null ? data["error_code"].ToString() : null;

                    _window.Dispatcher.BeginInvoke(new Action(() => {
                        _window.UpdateLogArea(msg, isError, errorCode);
                    }));

                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "ok" } });
                }
                else if (path == "/api/overlay" && request.HttpMethod == "POST")
                {
                    string body = ReadRequestBody(request);
                    var data = DeserializeJson(body);
                    string text = data.ContainsKey("text") ? data["text"].ToString() : "";
                    string imagePath = data.ContainsKey("image_path") ? data["image_path"].ToString() : "";
                    
                    double alphaVal = 0.6;
                    if (data.ContainsKey("alpha_val") && data["alpha_val"] != null)
                    {
                        double.TryParse(data["alpha_val"].ToString(), out alphaVal);
                    }
                    
                    double displayTime = 60.0;
                    if (data.ContainsKey("display_time") && data["display_time"] != null)
                    {
                        double.TryParse(data["display_time"].ToString(), out displayTime);
                    }

                    string status = data.ContainsKey("status") ? data["status"].ToString() : "speaking";

                    _window.Dispatcher.BeginInvoke(new Action(() => {
                        _window.ShowOverlay(text, imagePath, alphaVal, displayTime, status);
                    }));

                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "ok" } });
                }
                else if ((path == "/api/translate" || path == "/api/rtt_toggle") && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    // Check RTT Core status, then toggle
                    bool rttRunning = false;
                    try
                    {
                        string statusUrl = "http://127.0.0.1:5001/api/status";
                        var statusData = DeserializeJson(ForwardGetRequest(statusUrl));
                        rttRunning = statusData.ContainsKey("is_running") && Convert.ToBoolean(statusData["is_running"]);
                    }
                    catch { }

                    string actionTaken = "";
                    _window.Dispatcher.Invoke(new Action(() => {
                        if (rttRunning)
                        {
                            _window.RttStop();
                            actionTaken = "stop";
                        }
                        else
                        {
                            _window.RttStart();
                            actionTaken = "start";
                        }
                    }));

                    responseString = SerializeJson(new Dictionary<string, object> {
                        { "status", "ok" },
                        { "action", actionTaken }
                    });
                }
                else if (path == "/api/retrans" && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    responseString = ForwardPostRequest("http://127.0.0.1:5001/api/retrans", "");
                }
                else if (path == "/api/status" && request.HttpMethod == "GET")
                {
                    bool isRttProcessRunning = false;
                    _window.Dispatcher.Invoke(new Action(() => {
                        isRttProcessRunning = _window.IsRttProcessRunning();
                    }));

                    var statusData = new Dictionary<string, object>
                    {
                        { "status", "ok" },
                        { "version", "1.2.0-beta" },
                        { "rtt_process", isRttProcessRunning ? "running" : "stopped" }
                    };

                    if (isRttProcessRunning)
                    {
                        try
                        {
                            statusData["rtt_detail"] = DeserializeJson(ForwardGetRequest("http://127.0.0.1:5001/api/status"));
                        }
                        catch
                        {
                            statusData["rtt_detail"] = "api_not_ready";
                        }
                    }

                    responseString = SerializeJson(statusData);
                }
                else if (path == "/api/rtt_start" && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    _window.Dispatcher.BeginInvoke(new Action(() => {
                        _window.RttStart();
                    }));
                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "ok" }, { "action", "rtt_start" } });
                }
                else if (path == "/api/rtt_stop" && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    _window.Dispatcher.BeginInvoke(new Action(() => {
                        _window.RttStop();
                    }));
                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "ok" }, { "action", "rtt_stop" } });
                }
                else if (path == "/api/rtt_status" && request.HttpMethod == "GET")
                {
                    try
                    {
                        responseString = ForwardGetRequest("http://127.0.0.1:5001/api/status");
                    }
                    catch
                    {
                        responseString = SerializeJson(new Dictionary<string, object> { { "status", "ok" }, { "is_running", false }, { "error", "RTT not connected" } });
                    }
                }
                else if (path == "/api/rtt_retrans" && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    try
                    {
                        responseString = ForwardPostRequest("http://127.0.0.1:5001/api/retrans", "");
                    }
                    catch (Exception ex)
                    {
                        statusCode = (int)HttpStatusCode.BadGateway;
                        responseString = SerializeJson(new Dictionary<string, object> { { "status", "error" }, { "message", ex.Message } });
                    }
                }
                else if (path == "/api/ecomode" && (request.HttpMethod == "POST" || request.HttpMethod == "GET"))
                {
                    string ecoState = "off";
                    _window.Dispatcher.Invoke(new Action(() => {
                        _window.ToggleRttEcoMode();
                        ecoState = _window.IsEcoModeOn() ? "on" : "off";
                    }));
                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "success" }, { "ecomode", ecoState } });
                }
                else if (path == "/api/session" && request.HttpMethod == "GET")
                {
                    string currentSession = "";
                    _window.Dispatcher.Invoke(new Action(() => {
                        currentSession = _window.GetActiveSessionId();
                    }));
                    responseString = SerializeJson(new Dictionary<string, object> {
                        { "status", "ok" },
                        { "session_id", currentSession }
                    });
                }
                else if (path.StartsWith("/api/"))
                {
                    // Generic action handler /api/<action>
                    string action = path.Substring(5);
                    _window.Dispatcher.BeginInvoke(new Action(() => {
                        _window.TriggerRemoteAction(action);
                    }));
                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "success" }, { "action", action } });
                }
                else
                {
                    statusCode = (int)HttpStatusCode.NotFound;
                    responseString = SerializeJson(new Dictionary<string, object> { { "status", "error" }, { "message", "Endpoint not found" } });
                }
            }
            catch (Exception ex)
            {
                statusCode = (int)HttpStatusCode.InternalServerError;
                responseString = SerializeJson(new Dictionary<string, object> { { "status", "error" }, { "message", ex.Message } });
            }

            try
            {
                byte[] buffer = Encoding.UTF8.GetBytes(responseString);
                response.ContentLength64 = buffer.Length;
                response.ContentType = "application/json; charset=utf-8";
                response.StatusCode = statusCode;
                response.OutputStream.Write(buffer, 0, buffer.Length);
                response.OutputStream.Close();
            }
            catch { }
        }

        private string ReadRequestBody(HttpListenerRequest request)
        {
            using (var reader = new StreamReader(request.InputStream, request.ContentEncoding))
            {
                return reader.ReadToEnd();
            }
        }

        private Dictionary<string, object> DeserializeJson(string json)
        {
            if (string.IsNullOrEmpty(json)) return new Dictionary<string, object>();
            try
            {
                var serializer = new JavaScriptSerializer();
                return serializer.Deserialize<Dictionary<string, object>>(json) ?? new Dictionary<string, object>();
            }
            catch
            {
                return new Dictionary<string, object>();
            }
        }

        private string SerializeJson(object obj)
        {
            var serializer = new JavaScriptSerializer();
            return serializer.Serialize(obj);
        }

        private string ForwardGetRequest(string url)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "GET";
            request.Timeout = 2000;
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            {
                return reader.ReadToEnd();
            }
        }

        private string ForwardPostRequest(string url, string postData)
        {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
            request.Method = "POST";
            request.Timeout = 2000;
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
    }
}
