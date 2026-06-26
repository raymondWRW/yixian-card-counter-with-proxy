// Spine facade — core Spine runtime types
using System;

namespace Spine
{
    public class ExposedList<T> { public T[] Items; public int Count; public ExposedList() { Items = new T[0]; Count = 0; } public void Add(T item) { } public void Clear() { Count = 0; } }

    public class Skeleton
    {
        public Bone RootBone => null; public SkeletonData Data => null;
        public float ScaleX { get; set; } public float ScaleY { get; set; }
        public float X { get; set; } public float Y { get; set; }
        public Skin Skin { get; set; }
        public ExposedList<Slot> Slots { get; set; } public ExposedList<Slot> DrawOrder { get; set; } public ExposedList<Bone> Bones { get; set; }
        public void SetSkin(string n) { } public void SetSkin(Skin s) { }
        public void SetSlotsToSetupPose() { } public void SetBonesToSetupPose() { } public void SetToSetupPose() { }
        public void UpdateWorldTransform() { }
        public Bone FindBone(string n) => null; public Slot FindSlot(string n) => null;
        public Attachment GetAttachment(string s, string a) => null; public Attachment GetAttachment(int s, string a) => null;
        public void SetAttachment(string s, string a) { }
        public Color color;
    }

    public class SkeletonData
    {
        public string Name { get; set; }
        public ExposedList<BoneData> Bones { get; set; } public ExposedList<SlotData> Slots { get; set; }
        public ExposedList<Skin> Skins { get; set; } public Skin DefaultSkin { get; set; }
        public ExposedList<Animation> Animations { get; set; }
        public float Width { get; set; } public float Height { get; set; }
        public Animation FindAnimation(string n) => null; public Skin FindSkin(string n) => null;
        public BoneData FindBone(string n) => null;
    }

    public class Animation { public string Name { get; set; } public float Duration { get; set; } }

    public class AnimationState
    {
        public AnimationStateData Data { get; set; }
        public ExposedList<TrackEntry> Tracks { get; set; }
        public float TimeScale { get; set; }
        public TrackEntry SetAnimation(int i, string n, bool l) => new TrackEntry();
        public TrackEntry SetAnimation(int i, Animation a, bool l) => new TrackEntry();
        public TrackEntry AddAnimation(int i, string n, bool l, float d) => new TrackEntry();
        public TrackEntry AddAnimation(int i, Animation a, bool l, float d) => new TrackEntry();
        public TrackEntry SetEmptyAnimation(int i, float m) => new TrackEntry();
        public void AddEmptyAnimation(int i, float m, float d) { }
        public TrackEntry GetCurrent(int i) => null;
        public void ClearTracks() { } public void ClearTrack(int i) { }
        public void Update(float d) { } public void Apply(Skeleton s) { }
        public event TrackEntryDelegate Start; public event TrackEntryDelegate Interrupt;
        public event TrackEntryDelegate End; public event TrackEntryDelegate Dispose;
        public event TrackEntryDelegate Complete; public event TrackEntryEventDelegate Event;
        public delegate void TrackEntryDelegate(TrackEntry e);
        public delegate void TrackEntryEventDelegate(TrackEntry e, Event ev);
    }

    public class AnimationStateData
    {
        public SkeletonData SkeletonData { get; set; } public float DefaultMix { get; set; }
        public AnimationStateData() { } public AnimationStateData(SkeletonData d) { SkeletonData = d; }
        public void SetMix(string f, string t, float d) { } public float GetMix(Animation f, Animation t) => DefaultMix;
    }

    public class TrackEntry
    {
        public int TrackIndex { get; set; } public Animation Animation { get; set; }
        public bool Loop { get; set; } public float Delay { get; set; }
        public float TrackTime { get; set; } public float TrackEnd { get; set; }
        public float AnimationStart { get; set; } public float AnimationEnd { get; set; }
        public float AnimationLast { get; set; } public float AnimationTime { get; set; }
        public float TimeScale { get; set; } public float Alpha { get; set; }
        public float MixTime { get; set; } public float MixDuration { get; set; }
        public TrackEntry MixingFrom { get; set; } public TrackEntry Next { get; set; }
        public bool IsComplete => true; public float MixBlend { get; set; }
        public event AnimationState.TrackEntryDelegate Start;
        public event AnimationState.TrackEntryDelegate Interrupt;
        public event AnimationState.TrackEntryDelegate End;
        public event AnimationState.TrackEntryDelegate Dispose;
        public event AnimationState.TrackEntryDelegate Complete;
        public event AnimationState.TrackEntryEventDelegate Event;
    }

    public class Event { public EventData Data { get; set; } public float Time { get; set; } public int IntValue { get; set; } public float FloatValue { get; set; } public string StringValue { get; set; } }
    public class EventData { public string Name { get; set; } public EventData(string n) { Name = n; } }

    public class Bone { public BoneData Data { get; set; } public Bone Parent { get; set; } public float X { get; set; } public float Y { get; set; } public float Rotation { get; set; } public float ScaleX { get; set; } public float ScaleY { get; set; } public float WorldX { get; set; } public float WorldY { get; set; } }
    public class BoneData { public int Index { get; set; } public string Name { get; set; } public BoneData Parent { get; set; } public BoneData(int i, string n, BoneData p) { Index = i; Name = n; Parent = p; } }
    public class Slot { public SlotData Data { get; set; } public Bone Bone { get; set; } public Attachment Attachment { get; set; } public Color color; }
    public class SlotData { public int Index { get; set; } public string Name { get; set; } public BoneData BoneData { get; set; } public SlotData(int i, string n, BoneData b) { Index = i; Name = n; BoneData = b; } }
    public class Skin { public string Name { get; set; } public Skin(string n) { Name = n; } public Attachment GetAttachment(int s, string n) => null; public void SetAttachment(int s, string n, Attachment a) { } }
    public abstract class Attachment { public string Name { get; set; } }
    public class RegionAttachment : Attachment { public float X { get; set; } public float Y { get; set; } public float Width { get; set; } public float Height { get; set; } public float Rotation { get; set; } public float ScaleX { get; set; } public float ScaleY { get; set; } }
    public class MeshAttachment : Attachment { }

    public struct Color { public float r, g, b, a; public Color(float r, float g, float b, float a) { this.r = r; this.g = g; this.b = b; this.a = a; } }
    public class AtlasAssetBase { }
}
namespace Spine { public delegate void TrackEntryEventDelegate(Spine.TrackEntry e, Spine.Event ev); }
