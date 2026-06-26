// Cinemachine facade
using UnityEngine;

namespace Cinemachine
{
    public abstract class CinemachineVirtualCameraBase : MonoBehaviour { public int Priority { get; set; } public GameObject VirtualCameraGameObject => gameObject; }
    public class CinemachineVirtualCamera : CinemachineVirtualCameraBase { public float m_Lens_FieldOfView { get; set; } public float m_Lens_OrthographicSize { get; set; } public Transform Follow { get; set; } public Transform LookAt { get; set; } }
    public class CinemachineBrain : MonoBehaviour { public static CinemachineBrain Instance { get; set; } }
    public class CinemachineImpulseSource : MonoBehaviour { public void GenerateImpulse() { } public void GenerateImpulse(float f) { } public void GenerateImpulse(Vector3 v) { } }
    public class CinemachineConfiner : MonoBehaviour { public Collider2D m_BoundingShape2D { get; set; } }
    public class CinemachineTransposer : MonoBehaviour { public Vector3 m_FollowOffset { get; set; } }
    public class CinemachineFramingTransposer : MonoBehaviour { public float m_ScreenX { get; set; } public float m_ScreenY { get; set; } public float m_DeadZoneWidth { get; set; } }
    public class NoiseSettings : ScriptableObject { }
    public class CinemachineBasicMultiChannelPerlin : MonoBehaviour { public NoiseSettings m_NoiseProfile; public float m_AmplitudeGain; public float m_FrequencyGain; }
}
