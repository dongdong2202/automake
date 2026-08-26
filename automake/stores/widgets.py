import json
from django import forms
from django.utils.safestring import mark_safe

class BusinessHoursWidget(forms.Widget):
    """
    图形化营业时间选择器组件
    """
    def __init__(self, attrs=None):
        default_attrs = {'class': 'vLargeTextField'}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    def render(self, name, value, attrs=None, renderer=None):
        # 解析当前的 JSON 值
        if isinstance(value, str):
            try:
                value_dict = json.loads(value)
            except json.JSONDecodeError:
                value_dict = {}
        elif isinstance(value, dict):
            value_dict = value
        else:
            value_dict = {}

        # 默认营业时间段配置
        default_value = {
            "mon": "09:00-22:00",
            "tue": "09:00-22:00",
            "wed": "09:00-22:00",
            "thu": "09:00-22:00",
            "fri": "09:00-22:00",
            "sat": "09:00-22:00",
            "sun": "09:00-22:00",
        }
        for k, v in default_value.items():
            if k not in value_dict:
                value_dict[k] = v

        days = [
            ("mon", "星期一"),
            ("tue", "星期二"),
            ("wed", "星期三"),
            ("thu", "星期四"),
            ("fri", "星期五"),
            ("sat", "星期六"),
            ("sun", "星期日"),
        ]

        html = []
        textarea_id = attrs.get('id', f'id_{name}')
        
        # 隐藏的 textarea 存储真实提交数据，通过 JS 实时同步
        html.append(f'<textarea name="{name}" id="{textarea_id}" style="display:none;">{json.dumps(value_dict)}</textarea>')

        # 图形化容器，采用契合 django-unfold 的暗色和圆角风格
        html.append('<div class="business-hours-picker" style="background:#1e293b; color:#f8fafc; border:1px solid #334155; border-radius:8px; padding:16px; font-family:sans-serif; max-width:600px; margin-top:5px;">')
        
        # 快捷按钮栏
        html.append('<div style="display:flex; gap:10px; margin-bottom:15px; border-bottom:1px solid #475569; padding-bottom:10px;">')
        html.append('<button type="button" onclick="setAllHours(\'09:00-22:00\')" style="background:#3b82f6; color:#fff; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px;">统一工作时间 (09:00-22:00)</button>')
        html.append('<button type="button" onclick="setAllHours(\'08:00-23:00\')" style="background:#10b981; color:#fff; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px;">统一延长营业 (08:00-23:00)</button>')
        html.append('<button type="button" onclick="setAllWeekendClosed()" style="background:#ef4444; color:#fff; border:none; padding:4px 10px; border-radius:4px; cursor:pointer; font-size:12px;">周末休息（不营业）</button>')
        html.append('</div>')

        # 每日营业时间配置行
        for day_code, day_name in days:
            time_val = value_dict.get(day_code, "09:00-22:00")
            is_closed = time_val == "closed"
            
            start_time = "09:00"
            end_time = "22:00"
            if not is_closed and "-" in time_val:
                parts = time_val.split("-")
                if len(parts) == 2:
                    start_time, end_time = parts

            html.append(f'<div class="day-row" data-day="{day_code}" style="display:flex; align-items:center; gap:12px; margin-bottom:10px; font-size:14px;">')
            html.append(f'<span style="width:70px; font-weight:bold; color:#94a3b8;">{day_name}</span>')
            
            # 是否营业开关复选框
            checked_str = 'checked' if not is_closed else ''
            html.append(f'<label style="display:flex; align-items:center; gap:4px; cursor:pointer; color:#f8fafc;"><input type="checkbox" class="day-enabled" {checked_str} onchange="updateBusinessHoursJson()" style="cursor:pointer; width:16px; height:16px;"> 营业</label>')
            
            # 具体营业时间选择
            disabled_str = 'disabled' if is_closed else ''
            opacity_val = '0.5' if is_closed else '1'
            html.append(f'<div class="time-inputs-wrap" style="display:flex; align-items:center; gap:6px; opacity:{opacity_val}; transition: opacity 0.2s;">')
            html.append(f'<input type="time" class="start-time" value="{start_time}" {disabled_str} onchange="updateBusinessHoursJson()" style="background:#334155; color:#fff; border:1px solid #475569; border-radius:4px; padding:2px 6px; cursor:pointer;">')
            html.append('<span style="color:#64748b;">至</span>')
            html.append(f'<input type="time" class="end-time" value="{end_time}" {disabled_str} onchange="updateBusinessHoursJson()" style="background:#334155; color:#fff; border:1px solid #475569; border-radius:4px; padding:2px 6px; cursor:pointer;">')
            html.append('</div>')
            
            html.append('</div>')

        html.append('</div>')

        # 动态转换机制 JS 脚本
        html.append(f"""
<script>
(function() {{
    function updateBusinessHoursJson() {{
        const wrapper = document.querySelector('.business-hours-picker');
        if (!wrapper) return;
        
        const rows = wrapper.querySelectorAll('.day-row');
        const result = {{}};
        
        rows.forEach(row => {{
            const day = row.getAttribute('data-day');
            const enabled = row.querySelector('.day-enabled').checked;
            const start = row.querySelector('.start-time');
            const end = row.querySelector('.end-time');
            const timeWrap = row.querySelector('.time-inputs-wrap');
            
            if (enabled) {{
                start.disabled = false;
                end.disabled = false;
                timeWrap.style.opacity = '1';
                result[day] = start.value + '-' + end.value;
            }} else {{
                start.disabled = true;
                end.disabled = true;
                timeWrap.style.opacity = '0.5';
                result[day] = 'closed';
            }}
        }});
        
        const textEl = document.getElementById('{textarea_id}');
        if (textEl) {{
            textEl.value = JSON.stringify(result);
        }}
    }}

    window.updateBusinessHoursJson = updateBusinessHoursJson;

    window.setAllHours = function(timeStr) {{
        const wrapper = document.querySelector('.business-hours-picker');
        if (!wrapper) return;
        
        const parts = timeStr.split('-');
        if (parts.length !== 2) return;
        
        const rows = wrapper.querySelectorAll('.day-row');
        rows.forEach(row => {{
            row.querySelector('.day-enabled').checked = true;
            row.querySelector('.start-time').value = parts[0];
            row.querySelector('.end-time').value = parts[1];
        }});
        updateBusinessHoursJson();
    }};

    window.setAllWeekendClosed = function() {{
        const wrapper = document.querySelector('.business-hours-picker');
        if (!wrapper) return;
        
        const rows = wrapper.querySelectorAll('.day-row');
        rows.forEach(row => {{
            const day = row.getAttribute('data-day');
            if (day === 'sat' || day === 'sun') {{
                row.querySelector('.day-enabled').checked = false;
            }}
        }});
        updateBusinessHoursJson();
    }};

    // 延时初始化以确保元素已经全部挂载并被 Django 渲染
    setTimeout(updateBusinessHoursJson, 100);
}})();
</script>
        """)

        return mark_safe('\n'.join(html))
