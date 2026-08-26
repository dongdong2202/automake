import os
from PIL import Image, ImageDraw, ImageFont

images_dir = "/home/ubuntu/autoMachine/webmin/images"
os.makedirs(images_dir, exist_ok=True)

def create_banner(filename, text, subtext, bg_gradient_start, bg_gradient_end, accent_color):
    width, height = 750, 360
    img = Image.new('RGB', (width, height), bg_gradient_start)
    draw = ImageDraw.Draw(img)
    
    # Draw gradient background
    for y in range(height):
        ratio = y / height
        r = int(bg_gradient_start[0] * (1 - ratio) + bg_gradient_end[0] * ratio)
        g = int(bg_gradient_start[1] * (1 - ratio) + bg_gradient_end[1] * ratio)
        b = int(bg_gradient_start[2] * (1 - ratio) + bg_gradient_end[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    # Decorative shapes
    draw.rounded_rectangle([40, 40, width - 40, height - 40], radius=24, outline=(255, 255, 255, 60), width=2)
    draw.ellipse([width - 240, 30, width - 40, 230], fill=accent_color)
    draw.ellipse([width - 200, 70, width - 80, 190], fill=(255, 255, 255, 180))
    
    # Badge
    draw.rounded_rectangle([70, 70, 210, 110], radius=20, fill=(255, 255, 255))
    
    # Try default font
    try:
        font_large = ImageFont.load_default()
    except Exception:
        font_large = None

    # Text
    draw.text((85, 80), "HOT · 新品上市", fill=(40, 40, 40))
    draw.text((70, 140), text, fill=(255, 255, 255))
    draw.text((70, 200), subtext, fill=(240, 240, 240))
    draw.text((70, 255), "▶ 立即前往选购", fill=(255, 220, 100))
    
    img.save(os.path.join(images_dir, filename), quality=95)
    print(f"Generated {filename}")

def create_product(filename, title, category_name, color):
    width, height = 400, 400
    img = Image.new('RGB', (width, height), (248, 249, 250))
    draw = ImageDraw.Draw(img)
    
    # Background circle
    draw.ellipse([40, 40, 360, 360], fill=color)
    
    # Inner cup illustration
    draw.polygon([(150, 120), (250, 120), (230, 290), (170, 290)], fill=(255, 255, 255))
    # Cup sleeve
    draw.polygon([(155, 180), (245, 180), (238, 235), (162, 235)], fill=(60, 60, 60))
    # Straw
    draw.line([(195, 70), (205, 140)], fill=(255, 100, 100), width=8)
    
    # Label badge
    draw.rounded_rectangle([100, 320, 300, 365], radius=12, fill=(30, 30, 30))
    draw.text((120, 332), f"{title} · {category_name}", fill=(255, 255, 255))
    
    img.save(os.path.join(images_dir, filename), quality=95)
    print(f"Generated {filename}")

def create_avatar(filename):
    width, height = 200, 200
    img = Image.new('RGB', (width, height), (235, 240, 245))
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, 180, 180], fill=(74, 144, 226))
    # Head
    draw.ellipse([70, 45, 130, 105], fill=(255, 255, 255))
    # Body
    draw.pieslice([40, 100, 160, 220], start=180, end=360, fill=(255, 255, 255))
    img.save(os.path.join(images_dir, filename), quality=95)
    print(f"Generated {filename}")

def create_empty(filename, title):
    width, height = 400, 400
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Light circle
    draw.ellipse([80, 80, 320, 320], fill=(245, 247, 250))
    # Box/Bag
    draw.rounded_rectangle([130, 150, 270, 270], radius=16, fill=(210, 215, 225))
    draw.line([(160, 150), (160, 120)], fill=(180, 185, 195), width=6)
    draw.line([(240, 150), (240, 120)], fill=(180, 185, 195), width=6)
    draw.arc([160, 90, 240, 150], start=180, end=360, fill=(180, 185, 195), width=6)
    draw.text((150, 340), title, fill=(160, 165, 175))
    img.save(os.path.join(images_dir, filename), quality=95)
    print(f"Generated {filename}")

if __name__ == '__main__':
    create_banner("banner1.png", "秋季桂花乌龙鲜奶茶", "精选高山原叶乌龙，现萃茶香浓郁", (217, 119, 6), (180, 83, 9), (251, 191, 36))
    create_banner("banner2.png", "大师现磨经典美式", "100% 阿拉比卡金奖咖啡豆", (51, 65, 85), (30, 41, 59), (148, 163, 184))
    create_banner("banner3.png", "鲜果手捣多肉葡萄", "新鲜大颗果肉 · 现制清爽冰沙", (147, 51, 234), (107, 33, 168), (192, 132, 252))
    
    create_product("drink_coffee.png", "经典咖啡", "现磨美式/拿铁", (220, 180, 140))
    create_product("drink_tea.png", "鲜萃奶茶", "原叶乌龙/茉莉", (245, 205, 160))
    create_product("drink_fruit.png", "芝士果茶", "多肉葡萄/草莓", (255, 180, 190))
    create_product("drink_special.png", "季节限定", "秋季特调", (210, 230, 210))
    
    create_avatar("default_avatar.png")
    create_empty("empty_order.png", "暂无历史订单")
    create_empty("empty_cart.png", "购物车空空如也")
