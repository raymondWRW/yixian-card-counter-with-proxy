# -*- coding: utf-8 -*-
"""单一事实源:每个对外 API 一条声明。Client 遍历这张表生成命名空间方法。
加一个新 API = C# 面板加一个方法 + 这里加一行 ApiSpec。

Ported from the game-api branch (Airexplosion/yixian-card-counter@game-api).
The live counter only uses the read subset (scene.current / placement.board /
state.round / state.self / game_status.req); the action methods are included
for standalone use / future automation."""
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ApiSpec:
    namespace: str          # python 子命名空间 (battle/scene/...)
    name: str               # python 方法名 (skip/board/...)
    ctype: str              # C# 类型全名 (YiXianBot.PlacementApi)
    cmethod: str            # C# 方法名 (Board)
    call: str               # "call_s"(int 参数) | "call_str"(字符串参数)
    ret: str                # "status"(ok:/EX:) | "json"(读盘类)
    args: List[str] = field(default_factory=list)
    doc: str = ""
    state_dep: str = ""     # 场景依赖, e.g. "修炼阶段"; 空=任意场景


T_BATTLE = "YiXianBot.BattleApi"
T_SCENE = "YiXianBot.SceneApi"
T_GS = "YiXianBot.GameStatusApi"
T_NET = "YiXianBot.NetworkApi"
T_STATE = "YiXianBot.StateApi"
T_PLACE = "YiXianBot.PlacementApi"

API: List[ApiSpec] = [
    ApiSpec("battle", "skip", T_BATTLE, "Skip", "call_s", "status", [],
            "跳过当前战斗动画,正常回到摆牌(发牌+加换牌次数)", "斗法阶段"),
    ApiSpec("battle", "force_break", T_BATTLE, "ForceBreak", "call_s", "status", [],
            "强制打断所有执行中的战斗执行器(不切场景)", "斗法阶段"),
    ApiSpec("battle", "is_battling", T_BATTLE, "IsBattling", "call_s", "status", [],
            "当前是否有战斗动画在播放(ok:1/ok:0)"),
    ApiSpec("scene", "change", T_SCENE, "Change", "call_s", "status", ["scene_type"],
            "切换场景:0=修炼阶段(摆牌) 1=斗法阶段(战斗)"),
    ApiSpec("scene", "current", T_SCENE, "Current", "call_s", "status", [],
            "当前场景枚举 int(0/1)"),
    ApiSpec("game_status", "req", T_GS, "Req", "call_s", "status", [],
            "向服务器请求当前权威对局状态(补发牌/换牌次数)"),
    ApiSpec("network", "auto_select", T_NET, "AutoSelect", "call_s", "status", ["ping_amount"],
            "自动选择最优线路"),
    ApiSpec("network", "analyze", T_NET, "Analyze", "call_s", "status", ["ping_amount"],
            "分析各线路延迟(不切),结果异步落库"),
    ApiSpec("network", "optimize", T_NET, "Optimize", "call_s", "status", [],
            "优化网络(会重载到 Home 场景,有打断性)"),
    ApiSpec("state", "round", T_STATE, "Round", "call_s", "json", [],
            "当前对局轮次 {round}"),
    ApiSpec("state", "self", T_STATE, "Self", "call_s", "json", [],
            "自身上一轮快照 {life,maxHp,tiPo,level}"),
    ApiSpec("placement", "board", T_PLACE, "Board", "call_s", "json", [],
            "当前手牌布局 {hand:[{slot,id}]},slot 用于 move/swap/refine 寻址", "修炼阶段"),
    ApiSpec("placement", "move", T_PLACE, "Move", "call_s", "status",
            ["hand_idx", "grid_idx"],
            "摆牌:把手牌第 hand_idx 张摆到棋盘格子第 grid_idx 个", "修炼阶段"),
    ApiSpec("placement", "swap", T_PLACE, "Swap", "call_s", "status", ["hand_idx"],
            "换牌:换掉手牌第 hand_idx 张", "修炼阶段"),
    ApiSpec("placement", "refine", T_PLACE, "Refine", "call_s", "status", ["hand_idx"],
            "炼化第 hand_idx 张手牌得修为", "修炼阶段"),
    ApiSpec("placement", "ready", T_PLACE, "Ready", "call_s", "status", [],
            "准备/确认结束本回合摆牌", "修炼阶段"),
    ApiSpec("placement", "fate_select", T_PLACE, "FateSelect", "call_s", "status", ["index"],
            "选天衍仙命:选第 index 个选项"),
    ApiSpec("placement", "daoyun_select", T_PLACE, "DaoyunSelect", "call_s", "status",
            ["daoyun_id"], "选道韵:选 daoyun_id"),
    ApiSpec("placement", "pact", T_PLACE, "Pact", "call_s", "status", ["kind", "param"],
            "通用弹窗选择 SimpleClientPact{kind,param}:仙命=26 天衍仙命=46 道韵=9 天命=5 失败再战=13 逃跑=0 rogue=11"),
    ApiSpec("placement", "select_career", T_PLACE, "SelectCareer", "call_s", "status",
            ["career", "random", "fzjx"],
            "选(副)职业:career 1炼丹2符咒3琴4画5阵法6灵植7命理;fzjx=1副职业;random=1随机"),
    ApiSpec("placement", "fate_branch_select", T_PLACE, "FateBranchSelect", "call_s", "status",
            ["index"], "选择仙命:选第 index 个选项(0起)"),
    ApiSpec("placement", "ui_select", T_PLACE, "UiSelect", "call_s", "status", ["index"],
            "真·UI选择:选项弹窗里选第index个Toggle+点ConfirmButton(index<0只点确定)"),
    ApiSpec("placement", "click_button", T_PLACE, "ClickButton", "call_str", "status", ["text"],
            "按可见文字点任意按钮(子串匹配)"),
    ApiSpec("placement", "breakthrough", T_PLACE, "Breakthrough", "call_s", "status", [],
            "突破:进入突破态;之后弹的天命/仙命用 ui_select 选"),
]
