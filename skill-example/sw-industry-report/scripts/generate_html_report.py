#!/usr/bin/env python3
"""
申万二级行业行情分析报告生成脚本（纯AKShare版本）
- 获取申万二级行业实时行情（使用AKShare，不需要iFinD）
- 生成HTML报告
"""

import akshare as ak
import warnings
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime



def get_sw_industries_basic():
    """获取申万二级行业基本信息"""
    df = ak.sw_index_second_info()
    df_dict = {}
    for _, row in df.iterrows():
        code = row['行业代码']
        df_dict[code] = {
            'name': row['行业名称'],
            'parent': row['上级行业'],
            'pe_ttm': row['TTM(滚动)市盈率'],
            'pb': row['市净率']
        }
    return df, df_dict


def get_realtime_quotes():
    """使用AKShare获取申万二级行业实时行情"""
    warnings.filterwarnings('ignore')
    df = ak.index_realtime_sw(symbol='二级行业')
    return df


def generate_html_report(quotes_df, df_dict):
    """生成HTML报告"""
    # 构建数据列表
    data = []
    for _, row in quotes_df.iterrows():
        code = row['指数代码']
        code_with_suffix = f"{code}.SI"
        info = df_dict.get(code_with_suffix, {})

        pre_close = row['昨收盘']
        latest = row['最新价']
        change = latest - pre_close
        change_ratio = (change / pre_close * 100) if pre_close > 0 else 0

        data.append({
            'code': code_with_suffix,
            'name': row['指数名称'],
            'parent': info.get('parent', ''),
            'latest': latest,
            'pre_close': pre_close,
            'change': change,
            'change_ratio': change_ratio,
            'pe_ttm': info.get('pe_ttm', 0),
            'pb': info.get('pb', 0),
            'volume': row['成交量'],
            'amount': row['成交额'],
            'high': row['最高价'],
            'low': row['最低价']
        })

    # 按涨跌幅排序
    data.sort(key=lambda x: x['change_ratio'], reverse=True)

    # 统计
    total = len(data)
    up_count = len([d for d in data if d['change_ratio'] > 0])
    down_count = len([d for d in data if d['change_ratio'] < 0])
    flat_count = total - up_count - down_count

    # HTML头部
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>申万二级行业行情分析</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); min-height: 100vh; padding: 20px; color: #fff; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ text-align: center; margin-bottom: 30px; padding: 30px; background: rgba(255,255,255,0.1); border-radius: 20px; }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; background: linear-gradient(90deg, #00d4ff, #7c3aed); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: rgba(255,255,255,0.1); border-radius: 15px; padding: 25px; text-align: center; }}
        .stat-card .value {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
        .stat-card .label {{ color: #a0a0a0; font-size: 0.9em; }}
        .stat-card.up .value {{ color: #ff4757; }}
        .stat-card.down .value {{ color: #2ed573; }}
        .stat-card.flat .value {{ color: #ffa502; }}
        .section {{ background: rgba(255,255,255,0.1); border-radius: 20px; padding: 25px; margin-bottom: 25px; }}
        .section h2 {{ font-size: 1.5em; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid rgba(255,255,255,0.2); }}
        .table-container {{ overflow-x: auto; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }}
        th {{ background: rgba(255,255,255,0.1); font-weight: 600; color: #00d4ff; }}
        tr:hover {{ background: rgba(255,255,255,0.05); }}
        .positive {{ color: #ff4757; }}
        .negative {{ color: #2ed573; }}
        .highlight-up {{ background: rgba(255, 71, 87, 0.2); }}
        .highlight-down {{ background: rgba(46, 213, 115, 0.2); }}
        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 0.9em; }}
        .color-legend {{ display: flex; justify-content: center; gap: 30px; margin-top: 15px; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; }}
        .legend-color {{ width: 20px; height: 20px; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>申万二级行业行情分析</h1>
            <p class="subtitle">数据更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <div class="color-legend">
                <div class="legend-item"><div class="legend-color" style="background:#ff4757"></div><span>涨幅（红色）</span></div>
                <div class="legend-item"><div class="legend-color" style="background:#2ed573"></div><span>跌幅（绿色）</span></div>
            </div>
        </div>
        <div class="stats">
            <div class="stat-card"><div class="value">{total}</div><div class="label">行业总数</div></div>
            <div class="stat-card up"><div class="value">{up_count}</div><div class="label">上涨行业</div></div>
            <div class="stat-card down"><div class="value">{down_count}</div><div class="label">下跌行业</div></div>
            <div class="stat-card flat"><div class="value">{flat_count}</div><div class="label">平盘行业</div></div>
        </div>
        <div class="section">
            <h2>涨幅前20行业</h2>
            <div class="table-container">
                <table>
                    <thead><tr><th>排名</th><th>行业名称</th><th>一级行业</th><th>最新点位</th><th>涨跌幅</th><th>涨跌点</th><th>成交量(万)</th><th>成交额(万)</th></tr></thead>
                    <tbody>'''

    # 涨幅前20
    for idx, item in enumerate(data[:20]):
        change_sign = '+' if item['change_ratio'] > 0 else ''
        html += f'''<tr class="highlight-up">
            <td>{idx+1}</td><td>{item['name']}</td><td>{item['parent']}</td>
            <td>{item['latest']:.2f}</td>
            <td class="positive">{change_sign}{item['change_ratio']:.2f}%</td>
            <td class="positive">{change_sign}{item['change']:.2f}</td>
            <td>{item['volume']:.2f}</td>
            <td>{item['amount']:.2f}</td>
        </tr>'''

    html += '''</tbody></table></div></div>'''

    # 跌幅前20
    html += '''<div class="section">
            <h2>跌幅前20行业</h2>
            <div class="table-container">
                <table>
                    <thead><tr><th>排名</th><th>行业名称</th><th>一级行业</th><th>最新点位</th><th>涨跌幅</th><th>涨跌点</th><th>成交量(万)</th><th>成交额(万)</th></tr></thead>
                    <tbody>'''

    for idx, item in enumerate(data[-20:][::-1]):
        change_sign = '+' if item['change_ratio'] > 0 else ''
        html += f'''<tr class="highlight-down">
            <td>{idx+1}</td><td>{item['name']}</td><td>{item['parent']}</td>
            <td>{item['latest']:.2f}</td>
            <td class="negative">{change_sign}{item['change_ratio']:.2f}%</td>
            <td class="negative">{change_sign}{item['change']:.2f}</td>
            <td>{item['volume']:.2f}</td>
            <td>{item['amount']:.2f}</td>
        </tr>'''

    html += '''</tbody></table></div></div>'''

    # 全部行业概览
    html += '''<div class="section">
            <h2>全部行业涨跌分布</h2>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 15px;">'''

    for item in data:
        change_sign = '+' if item['change_ratio'] > 0 else ''
        change_class = 'positive' if item['change_ratio'] > 0 else 'negative' if item['change_ratio'] < 0 else ''
        html += f'''<div style="background: rgba(255,255,255,0.05); border-radius: 12px; padding: 15px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <div style="font-weight: 600;">{item['name']}</div>
                <div style="font-size: 0.85em; color: #888;">{item['parent']}</div>
            </div>
            <div style="text-align: right;">
                <div class="{change_class}" style="font-size: 1.1em; font-weight: bold;">{change_sign}{item['change_ratio']:.2f}%</div>
                <div style="font-size: 0.85em; color: #888;">{item['latest']:.2f}</div>
            </div>
        </div>'''

    html += '''</div></div>'''

    # 页脚
    html += f'''<div class="footer"><p>数据来源：AKShare（申万宏源研究）</p></div>
    </div>
</body>
</html>'''

    return html



def main():
    print("开始获取申万二级行业数据...")

    # 1. 获取行业基本信息（用于行业分类名称）
    df, df_dict = get_sw_industries_basic()
    print(f"获取到 {len(df)} 个申万二级行业基本信息")

    # 2. 获取实时行情（使用AKShare，不需要iFinD）
    print("正在获取实时行情...")
    quotes_df = get_realtime_quotes()
    print(f"获取到 {len(quotes_df)} 条行情数据")

    # 3. 生成HTML报告
    html_report = generate_html_report(quotes_df, df_dict)
    print("HTML报告已生成")

    # 生成临时文件，存储html
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp_file:
        tmp_file.write(html_report)
        tmp_html_path = tmp_file.name
    print(f"HTML报告已保存到临时文件: {tmp_html_path}")


if __name__ == "__main__":
    main()