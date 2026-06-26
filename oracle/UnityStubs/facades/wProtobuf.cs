// wProtobuf — real protobuf-wire-format implementation for headless oracle
// Replaces no-op stubs with actual read/write operations so ConfigLoader can parse game configs.
using System;
using System.IO;
using System.Collections.Generic;
using System.Text;

namespace wProtobuf
{
    public interface IMessage { int CalculateSize(); void WriteTo(IWriteStream stream); void MergeFrom(IReadStream stream); }
    public interface IMessage<T> : IMessage where T : IMessage<T> { T Clone(); }

    public interface IWriteStream
    {
        void WriteBool(int f, bool v); void WriteInt32(int f, int v); void WriteUInt32(int f, uint v);
        void WriteInt64(int f, long v); void WriteUInt64(int f, ulong v);
        void WriteFloat(int f, float v); void WriteDouble(int f, double v);
        void WriteString(int f, string v); void WriteBytes(int f, byte[] v);
        void WriteEnum(int f, int v); void WriteMessage(int f, IMessage v);
        void WriteBool(bool v); void WriteInt32(int v); void WriteUInt32(uint v);
        void WriteFloat(float v); void WriteDouble(double v);
        void WriteString(string v); void WriteBytes(byte[] v); void WriteBytes(ByteString v);
        void WriteEnum(int v); void WriteMessage(IMessage v);
        void WriteRawTag(byte tag);
        void WriteRawTag(byte tag1, byte tag2);
        void WriteRawTag(byte t1, byte t2, byte t3);
        void WriteInt64(long v); void WriteUInt64(ulong v);
        void WriteMessage(Action action);
        void WriteMessage(int f, Action action);
    }

    public interface IReadStream
    {
        bool ReadBool(); int ReadInt32(); uint ReadUInt32(); long ReadInt64(); ulong ReadUInt64();
        float ReadFloat(); double ReadDouble(); string ReadString(); ByteString ReadBytes();
        int ReadEnum(); uint ReadTag(); bool IsAtEnd { get; } void SkipLastField(uint tag);
        void ReadMessage(IMessage msg);
        void ReadMessage(Action action);
        T ReadMessage<T>() where T : IMessage, new();
    }

    public sealed class ByteString
    {
        public static readonly ByteString Empty = new ByteString(Array.Empty<byte>());
        private readonly byte[] _bytes;
        public ByteString(byte[] bytes) { _bytes = bytes ?? Array.Empty<byte>(); }
        public byte[] ToByteArray() => _bytes;
        public int Length => _bytes.Length;
        public byte this[int i] => _bytes[i];
        public static implicit operator byte[](ByteString bs) => bs?._bytes ?? Array.Empty<byte>();
        public static implicit operator ByteString(byte[] bytes) => new ByteString(bytes);
    }

    internal static class Varint
    {
        public static int Write(byte[] buf, int pos, ulong value)
        {
            while (value > 0x7F) { buf[pos++] = (byte)((value & 0x7F) | 0x80); value >>= 7; }
            buf[pos++] = (byte)value;
            return pos;
        }
        public static (ulong value, int newPos) Read(byte[] buf, int pos, int limit)
        {
            ulong result = 0; int shift = 0;
            while (pos < limit)
            {
                byte b = buf[pos++];
                result |= (ulong)(b & 0x7F) << shift;
                if ((b & 0x80) == 0) return (result, pos);
                shift += 7;
                if (shift >= 64) throw new InvalidDataException("Varint too large");
            }
            throw new EndOfStreamException("Unexpected end of stream reading varint");
        }
    }

    public static class ComputeSize
    {
        public static int VarintSize(ulong v)
        {
            if (v < (1UL << 7)) return 1; if (v < (1UL << 14)) return 2;
            if (v < (1UL << 21)) return 3; if (v < (1UL << 28)) return 4;
            if (v < (1UL << 35)) return 5; if (v < (1UL << 42)) return 6;
            if (v < (1UL << 49)) return 7; if (v < (1UL << 56)) return 8;
            if (v < (1UL << 63)) return 9; return 10;
        }
        public static int Bool(bool v) => 1;
        public static int Int32(int v) => v >= 0 ? VarintSize((ulong)v) : 10;
        public static int UInt32(uint v) => VarintSize((ulong)v);
        public static int Int64(long v) => v >= 0 ? VarintSize((ulong)v) : 10;
        public static int UInt64(ulong v) => VarintSize(v);
        public static int Float(float v) => 4; public static int Double(double v) => 8;
        public static int Enum(int v) => Int32(v);
        public static int String(string v) { int len = v != null ? Encoding.UTF8.GetByteCount(v) : 0; return VarintSize((ulong)len) + len; }
        public static int Bytes(byte[] v) { int len = v != null ? v.Length : 0; return VarintSize((ulong)len) + len; }
        public static int Message(IMessage v) { if (v == null) return 0; int s = v.CalculateSize(); return VarintSize((ulong)s) + s; }
        public static int Tag(int f) => VarintSize((ulong)(f << 3));
        public static int ComputeStringSize(string v) => String(v);
        public static int ComputeBoolSize(bool v) => 1;
        public static int ComputeInt32Size(int v) => Int32(v);
        public static int ComputeUInt32Size(uint v) => UInt32(v);
        public static int ComputeInt64Size(long v) => Int64(v);
        public static int ComputeUInt64Size(ulong v) => UInt64(v);
        public static int ComputeFloatSize(float v) => 4;
        public static int ComputeDoubleSize(double v) => 8;
        public static int ComputeEnumSize(int v) => Enum(v);
        public static int ComputeMessageSize(IMessage v) => Message(v);
        public static int ComputeBytesSize(byte[] v) => Bytes(v);
        public static int Bytes(ByteString v) => Bytes(v?.ToByteArray());
        public static int ComputeBytesSize(ByteString v) => Bytes(v?.ToByteArray());
        public static int ComputeMessageSize(Action v) => 0;
    }

    public class WriteStream : IWriteStream
    {
        protected byte[] _buf;
        protected int _writePos;
        public WriteStream(int bufferSize) { _buf = new byte[bufferSize > 0 ? bufferSize : 256]; }
        public WriteStream(Stream s) { using var ms = new MemoryStream(); s.CopyTo(ms); _buf = ms.ToArray(); _writePos = _buf.Length; }
        public int WritePos { get => _writePos; set => _writePos = value; }

        protected void EnsureCapacity(int needed)
        {
            int required = _writePos + needed;
            if (required <= _buf.Length) return;
            Array.Resize(ref _buf, Math.Max(_buf.Length * 2, required + 256));
        }
        public void Write(byte[] data)
        {
            if (data == null || data.Length == 0) return;
            EnsureCapacity(data.Length);
            Buffer.BlockCopy(data, 0, _buf, _writePos, data.Length);
            _writePos += data.Length;
        }

        public void WriteRawTag(byte t) { EnsureCapacity(1); _buf[_writePos++] = t; }
        public void WriteRawTag(byte t1, byte t2) { EnsureCapacity(2); _buf[_writePos++] = t1; _buf[_writePos++] = t2; }
        public void WriteRawTag(byte t1, byte t2, byte t3) { EnsureCapacity(3); _buf[_writePos++] = t1; _buf[_writePos++] = t2; _buf[_writePos++] = t3; }

        protected void WriteVarint(ulong v) { EnsureCapacity(10); _writePos = Varint.Write(_buf, _writePos, v); }
        private void WriteTag(int f, int wt) => WriteVarint((ulong)((f << 3) | wt));

        public void WriteBool(int f, bool v) { WriteTag(f, 0); WriteBool(v); }
        public void WriteInt32(int f, int v) { WriteTag(f, 0); WriteInt32(v); }
        public void WriteUInt32(int f, uint v) { WriteTag(f, 0); WriteUInt32(v); }
        public void WriteInt64(int f, long v) { WriteTag(f, 0); WriteInt64(v); }
        public void WriteUInt64(int f, ulong v) { WriteTag(f, 0); WriteUInt64(v); }
        public void WriteFloat(int f, float v) { WriteTag(f, 5); WriteFloat(v); }
        public void WriteDouble(int f, double v) { WriteTag(f, 1); WriteDouble(v); }
        public void WriteString(int f, string v) { WriteTag(f, 2); WriteString(v); }
        public void WriteBytes(int f, byte[] v) { WriteTag(f, 2); WriteBytes(v); }
        public void WriteEnum(int f, int v) { WriteTag(f, 0); WriteEnum(v); }
        public void WriteMessage(int f, IMessage v) { if (v == null) return; WriteTag(f, 2); WriteMessage(v); }
        public void WriteMessage(int f, Action a) { WriteTag(f, 2); WriteMessage(a); }

        public void WriteBool(bool v) => WriteVarint(v ? 1UL : 0UL);
        public void WriteInt32(int v) => WriteVarint(v >= 0 ? (ulong)v : (ulong)(long)v);
        public void WriteUInt32(uint v) => WriteVarint(v);
        public void WriteInt64(long v) => WriteVarint((ulong)v);
        public void WriteUInt64(ulong v) => WriteVarint(v);
        public void WriteEnum(int v) => WriteVarint(v >= 0 ? (ulong)v : (ulong)(long)v);

        public void WriteFloat(float v)
        {
            EnsureCapacity(4); var b = BitConverter.GetBytes(v);
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            Buffer.BlockCopy(b, 0, _buf, _writePos, 4); _writePos += 4;
        }
        public void WriteDouble(double v)
        {
            EnsureCapacity(8); var b = BitConverter.GetBytes(v);
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            Buffer.BlockCopy(b, 0, _buf, _writePos, 8); _writePos += 8;
        }
        public void WriteString(string v)
        {
            if (v == null) v = "";
            var enc = Encoding.UTF8.GetBytes(v);
            WriteVarint((ulong)enc.Length);
            EnsureCapacity(enc.Length);
            Buffer.BlockCopy(enc, 0, _buf, _writePos, enc.Length);
            _writePos += enc.Length;
        }
        public void WriteBytes(byte[] v)
        {
            if (v == null) { WriteVarint(0); return; }
            WriteVarint((ulong)v.Length);
            EnsureCapacity(v.Length);
            Buffer.BlockCopy(v, 0, _buf, _writePos, v.Length);
            _writePos += v.Length;
        }
        public void WriteBytes(ByteString v) => WriteBytes(v?.ToByteArray());
        public void WriteMessage(IMessage v)
        {
            if (v == null) { WriteVarint(0); return; }
            var sub = new WriteStream(256); v.WriteTo(sub);
            var data = sub.ToByteArray();
            WriteVarint((ulong)data.Length);
            EnsureCapacity(data.Length);
            Buffer.BlockCopy(data, 0, _buf, _writePos, data.Length);
            _writePos += data.Length;
        }
        public void WriteMessage(Action action)
        {
            int startPos = _writePos;
            action();
            int writtenSize = _writePos - startPos;
            int varintLen = ComputeSize.VarintSize((ulong)writtenSize);
            EnsureCapacity(varintLen);
            Buffer.BlockCopy(_buf, startPos, _buf, startPos + varintLen, writtenSize);
            Varint.Write(_buf, startPos, (ulong)writtenSize);
            _writePos += varintLen;
        }
        public byte[] ToByteArray()
        {
            var r = new byte[_writePos]; Buffer.BlockCopy(_buf, 0, r, 0, _writePos); return r;
        }
    }

    public class ReadStream : IReadStream
    {
        protected byte[] _buf; protected int _readPos; protected int _limit;
        public ReadStream(byte[] data) { _buf = data ?? Array.Empty<byte>(); _limit = _buf.Length; }
        public ReadStream(Stream s) { using var ms = new MemoryStream(); s.CopyTo(ms); _buf = ms.ToArray(); _limit = _buf.Length; }
        public int ReadPos { get => _readPos; set => _readPos = value; }
        public bool IsAtEnd => _readPos >= _limit;

        private ulong ReadVarint()
        {
            var (v, p) = Varint.Read(_buf, _readPos, _limit); _readPos = p; return v;
        }
        public uint ReadTag() { if (IsAtEnd) return 0; return (uint)ReadVarint(); }
        public bool ReadBool() => ReadVarint() != 0;
        public int ReadInt32() => (int)(long)ReadVarint();
        public uint ReadUInt32() => (uint)ReadVarint();
        public long ReadInt64() => (long)ReadVarint();
        public ulong ReadUInt64() => ReadVarint();
        public int ReadEnum() => (int)(long)ReadVarint();
        public float ReadFloat()
        {
            var b = new byte[4]; Buffer.BlockCopy(_buf, _readPos, b, 0, 4); _readPos += 4;
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return BitConverter.ToSingle(b, 0);
        }
        public double ReadDouble()
        {
            var b = new byte[8]; Buffer.BlockCopy(_buf, _readPos, b, 0, 8); _readPos += 8;
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return BitConverter.ToDouble(b, 0);
        }
        public string ReadString()
        {
            int len = (int)ReadVarint(); if (len == 0) return "";
            string s = Encoding.UTF8.GetString(_buf, _readPos, len); _readPos += len; return s;
        }
        public ByteString ReadBytes()
        {
            int len = (int)ReadVarint(); if (len == 0) return ByteString.Empty;
            var d = new byte[len]; Buffer.BlockCopy(_buf, _readPos, d, 0, len); _readPos += len; return new ByteString(d);
        }
        public void ReadMessage(IMessage msg)
        {
            int len = (int)ReadVarint(); int saved = _limit; _limit = _readPos + len;
            msg.MergeFrom(this); _readPos = _limit; _limit = saved;
        }
        public void ReadMessage(Action action)
        {
            // Packed repeated fields: the delegate reads ONE element; loop until scope consumed.
            int len = (int)ReadVarint(); int saved = _limit; _limit = _readPos + len;
            while (_readPos < _limit) action();
            _readPos = _limit; _limit = saved;
        }
        public T ReadMessage<T>() where T : IMessage, new() { T m = new T(); ReadMessage((IMessage)m); return m; }
        public void SkipLastField(uint tag)
        {
            switch ((int)(tag & 0x7))
            {
                case 0: ReadVarint(); break;
                case 1: _readPos += 8; break;
                case 2: int len = (int)ReadVarint(); _readPos += len; break;
                case 5: _readPos += 4; break;
                default: throw new InvalidDataException($"Unknown wire type {tag & 0x7}");
            }
        }
    }

    // Combined read/write stream used by ConfigLoader
    public class MessageStream : WriteStream, IReadStream
    {
        private int _readPos2;
        private int _readLimit = int.MaxValue;
        public new int ReadPos { get => _readPos2; set => _readPos2 = value; }
        public MessageStream(int bufferSize) : base(bufferSize) { }
        public MessageStream(byte[] data) : base(data?.Length ?? 256)
        {
            if (data != null && data.Length > 0) Write(data);
        }

        public bool IsAtEnd => _readPos2 >= Math.Min(_writePos, _readLimit);

        private ulong ReadVarintInternal()
        {
            ulong result = 0; int shift = 0; int limit = Math.Min(_writePos, _readLimit);
            while (_readPos2 < limit)
            {
                byte b = _buf[_readPos2++];
                result |= (ulong)(b & 0x7F) << shift;
                if ((b & 0x80) == 0) return result;
                shift += 7;
                if (shift >= 64) throw new InvalidDataException("Varint too large");
            }
            throw new EndOfStreamException("Unexpected end of stream");
        }

        public uint ReadTag() { if (IsAtEnd) return 0; return (uint)ReadVarintInternal(); }
        public bool ReadBool() => ReadVarintInternal() != 0;
        public int ReadInt32() => (int)(long)ReadVarintInternal();
        public uint ReadUInt32() => (uint)ReadVarintInternal();
        public long ReadInt64() => (long)ReadVarintInternal();
        public ulong ReadUInt64() => ReadVarintInternal();
        public int ReadEnum() => (int)(long)ReadVarintInternal();
        public float ReadFloat()
        {
            var b = new byte[4]; Buffer.BlockCopy(_buf, _readPos2, b, 0, 4); _readPos2 += 4;
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return BitConverter.ToSingle(b, 0);
        }
        public double ReadDouble()
        {
            var b = new byte[8]; Buffer.BlockCopy(_buf, _readPos2, b, 0, 8); _readPos2 += 8;
            if (!BitConverter.IsLittleEndian) Array.Reverse(b);
            return BitConverter.ToDouble(b, 0);
        }
        public string ReadString()
        {
            int len = (int)ReadVarintInternal(); if (len == 0) return "";
            string s = Encoding.UTF8.GetString(_buf, _readPos2, len); _readPos2 += len; return s;
        }
        public ByteString ReadBytes()
        {
            int len = (int)ReadVarintInternal(); if (len == 0) return ByteString.Empty;
            var d = new byte[len]; Buffer.BlockCopy(_buf, _readPos2, d, 0, len); _readPos2 += len; return new ByteString(d);
        }
        public void ReadMessage(IMessage msg)
        {
            int len = (int)ReadVarintInternal(); int saved = _readLimit;
            _readLimit = _readPos2 + len;
            msg.MergeFrom(this); _readPos2 = _readLimit; _readLimit = saved;
        }
        public void ReadMessage(Action action)
        {
            // Packed repeated fields: the delegate reads ONE element; loop until scope consumed.
            int len = (int)ReadVarintInternal(); int saved = _readLimit;
            _readLimit = _readPos2 + len;
            while (_readPos2 < _readLimit) action();
            _readPos2 = _readLimit; _readLimit = saved;
        }
        public T ReadMessage<T>() where T : IMessage, new() { T m = new T(); ReadMessage((IMessage)m); return m; }
        public void SkipLastField(uint tag)
        {
            switch ((int)(tag & 0x7))
            {
                case 0: ReadVarintInternal(); break;
                case 1: _readPos2 += 8; break;
                case 2: int len = (int)ReadVarintInternal(); _readPos2 += len; break;
                case 5: _readPos2 += 4; break;
                default: throw new InvalidDataException($"Unknown wire type {tag & 0x7}");
            }
        }
    }

    public class MessageParser<T> where T : IMessage<T>, new()
    {
        private readonly Func<T> _factory;
        public MessageParser(Func<T> f) { _factory = f; }
        public T ParseFrom(byte[] d) { T m = _factory != null ? _factory() : new T(); m.MergeFrom(new ReadStream(d)); return m; }
        public T ParseFrom(IReadStream s) { T m = _factory != null ? _factory() : new T(); m.MergeFrom(s); return m; }
    }

    public class RepeatedField<T> : List<T> { public void Add(IEnumerable<T> values) { foreach (var v in values) base.Add(v); } }
    public class MapField<TKey, TValue> : Dictionary<TKey, TValue> { }

    // wProtobuf.Action — type-forwarded to System.Action
    // The game's generated protobuf code references this as wProtobuf.Action in IL
    public delegate void Action();
}

// ProtobufParser lives in the GLOBAL namespace in the game DLL (TypeRef.FullName == "ProtobufParser").
// It is the game's serialization entry point. The combat path reaches it via NetworkExtensions.Clone<T>
// (a protobuf serialize-roundtrip deep clone used when a card is shifted into play). We implement the
// real roundtrip using the message's own generated WriteTo/MergeFrom over our MessageStream, so the
// clone is a genuine independent copy — not a shared reference.
public class ProtobufParser
{
    public static ProtobufParser main { get; } = new ProtobufParser();

    // DecodeForILR (IL extension in NetworkExtensions) calls this, then writes bytes + MergeFrom.
    public wProtobuf.MessageStream GetDecodeStream() => new wProtobuf.MessageStream(256);
    public wProtobuf.MessageStream GetEncodeStream() => new wProtobuf.MessageStream(256);

    public byte[] Encode(wProtobuf.IMessage msg)
    {
        var s = new wProtobuf.MessageStream(256);
        msg.WriteTo(s);
        return s.ToByteArray();
    }

    public string EncodeToBase64(wProtobuf.IMessage msg) => System.Convert.ToBase64String(Encode(msg));
}
