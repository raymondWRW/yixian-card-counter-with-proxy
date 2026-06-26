// TapTap.Common facade
using System;
namespace TapTap.Common { public class TapException : Exception { public int Code { get; set; } public TapException(int c, string m) : base(m) { Code = c; } } }
