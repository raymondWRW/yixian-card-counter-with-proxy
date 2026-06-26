// DarkSun.Login facade
using System;
using UnityEngine;

namespace DarkSun.Login
{
    public class LoginManager : MonoBehaviour { public static LoginManager Instance { get; set; } public void Login(Action<bool> callback) { } public void Logout() { } }
    public class DarkSunUser { public string uid { get; set; } public string name { get; set; } public string token { get; set; } }
    public class JsonResponse<T> { public int code { get; set; } public string msg { get; set; } public T data { get; set; } }
    public class SimpleResponse { public int code { get; set; } public string msg { get; set; } }
}
