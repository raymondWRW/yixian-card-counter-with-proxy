// DarkTonic.MasterAudio facade
using UnityEngine;

namespace DarkTonic.MasterAudio
{
    public class MasterAudio : MonoBehaviour
    {
        public static MasterAudio Instance { get; set; }
        public static float MasterVolumeLevel { get; set; }
        public static void PlaySound(string s) { } public static void PlaySound(string s, float v) { }
        public static void PlaySoundAndForget(string s) { } public static void StopAllOfSound(string s) { }
        public static void FadeOutAllOfSound(string s, float t) { }
        public static void SetGroupVolume(string s, float v) { } public static float GetGroupVolume(string s) => 1;
        public static void MuteGroup(string s) { } public static void UnmuteGroup(string s) { }
        public static void StopMixer() { } public static void MuteEverything() { } public static void UnmuteEverything() { }
        public static bool SoundGroupExists(string s) => false;
        // Audio bus registry — empty headless; game code iterates it to find a bus by name.
        public static System.Collections.Generic.List<GroupBus> GroupBuses { get; } = new System.Collections.Generic.List<GroupBus>();
    }

    // Audio mixer bus — cosmetic. Game reads busName/volume; headless we keep an empty bus list.
    public class GroupBus
    {
        public string busName;
        public float volume;
        public float busVoiceLimit;
        public bool isMuted;
        public bool isSoloed;
    }
    public class PlaylistController : MonoBehaviour
    {
        public static PlaylistController InstanceByName(string n) => null;
        public string CurrentPlaylistName { get; set; } public void ChangePlaylist(string n) { }
        public void StartPlaylist() { } public void StopPlaylist() { }
    }
    public class SoundGroupVariation : MonoBehaviour { }
    public class DynamicSoundGroupCreator : MonoBehaviour { }
}
