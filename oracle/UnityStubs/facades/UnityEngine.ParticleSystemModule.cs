// UnityEngine.ParticleSystemModule facade
using UnityEngine;
namespace UnityEngine
{
    public class ParticleSystem : Component
    {
        public MainModule main => new MainModule();
        public EmissionModule emission => new EmissionModule();
        public bool isPlaying => false; public bool isStopped => true;
        public int particleCount => 0;
        public void Play() { } public void Play(bool w) { } public void Pause() { } public void Stop() { } public void Stop(bool w) { } public void Clear() { }
        public struct MainModule { public float duration { get; set; } public bool loop { get; set; } public MinMaxCurve startLifetime { get; set; } public MinMaxCurve startSpeed { get; set; } public MinMaxCurve startSize { get; set; } public MinMaxGradient startColor { get; set; } public float simulationSpeed { get; set; } public int maxParticles { get; set; } }
        public struct EmissionModule { public bool enabled { get; set; } public MinMaxCurve rateOverTime { get; set; } }
        public struct MinMaxCurve { public float constant; public MinMaxCurve(float c) { constant = c; } public static implicit operator MinMaxCurve(float v) => new MinMaxCurve(v); }
        public struct MinMaxGradient { public Color color; public MinMaxGradient(Color c) { color = c; } public static implicit operator MinMaxGradient(Color v) => new MinMaxGradient(v); }
    }
}
