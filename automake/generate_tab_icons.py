import os
from PIL import Image, ImageDraw

images_dir = "/home/ubuntu/autoMachine/webmin/images"

def create_tab_icon(filename, shape, active=False):
    width, height = 64, 64
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (255, 107, 0, 255) if active else (150, 150, 150, 255)
    
    if shape == 'home':
        # House
        draw.polygon([(32, 10), (12, 28), (52, 28)], fill=color)
        draw.rectangle([18, 28, 46, 54], fill=color)
        draw.rectangle([26, 36, 38, 54], fill=(255, 255, 255, 255) if not active else (255, 240, 230, 255))
    elif shape == 'menu':
        # Cup / Coffee
        draw.polygon([(18, 18), (46, 18), (42, 50), (22, 50)], fill=color)
        draw.arc([38, 24, 52, 38], start=270, end=90, fill=color, width=4)
        draw.line([(14, 18), (50, 18)], fill=color, width=4)
    elif shape == 'order':
        # Receipt / List
        draw.rounded_rectangle([18, 12, 46, 52], radius=4, fill=color)
        inner_c = (255, 255, 255, 255)
        draw.line([(24, 22), (40, 22)], fill=inner_c, width=3)
        draw.line([(24, 30), (40, 30)], fill=inner_c, width=3)
        draw.line([(24, 38), (34, 38)], fill=inner_c, width=3)
    elif shape == 'user':
        # Person
        draw.ellipse([24, 12, 40, 28], fill=color)
        draw.pieslice([14, 30, 50, 66], start=180, end=360, fill=color)
        
    img.save(os.path.join(images_dir, filename), 'PNG')
    print(f"Generated {filename}")

if __name__ == '__main__':
    create_tab_icon("tab_home.png", "home", False)
    create_tab_icon("tab_home_active.png", "home", True)
    create_tab_icon("tab_menu.png", "menu", False)
    create_tab_icon("tab_menu_active.png", "menu", True)
    create_tab_icon("tab_order.png", "order", False)
    create_tab_icon("tab_order_active.png", "order", True)
    create_tab_icon("tab_user.png", "user", False)
    create_tab_icon("tab_user_active.png", "user", True)
