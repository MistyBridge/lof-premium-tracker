"""分页上限必须装得下最大的板块。

前端是"一次拉全量 + 本地排序/筛选/分页"的架构：拉不全不只是少几只基金，
"溢价率降序"、KPI 统计、搜索都只在拉回来的那部分里算，榜单会直接失真。

历史上这个上限是 1500，而 ETF 全集约 1700 只 —— ETF 板块会静默漏掉一截。
"""
from constants import PAGE_SIZE_MAX


def test_page_size_max_fits_largest_board():
    """ETF 全集约 1700 只（含待上市），上限必须留出余量。"""
    assert PAGE_SIZE_MAX >= 2000


def test_router_and_service_caps_agree():
    """路由层的 Query(le=...) 与服务层的 min(size, PAGE_SIZE_MAX) 不能打架：
    路由放行 3000、服务层却截到 1500 时，客户端只会看到"返回条数比要的少"，
    不会有任何报错 —— 这类静默截断最难排查。"""
    import inspect

    from constants import PAGE_SIZE_MAX as cap
    from routers import funds as funds_router
    from services.fund_service import get_fund_list

    # 路由签名里的 le=
    sig = inspect.signature(funds_router.list_funds)
    size_param = sig.parameters["size"]
    router_cap = None
    for meta in size_param.default.metadata:
        if hasattr(meta, "le"):
            router_cap = meta.le
    assert router_cap is not None, "路由层应显式声明 size 上限"
    assert router_cap <= cap or router_cap == cap, \
        f"路由上限 {router_cap} 不应大于服务层上限 {cap}"
    assert callable(get_fund_list)
