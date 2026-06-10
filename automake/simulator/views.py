from django.shortcuts import render
from django.views import View

# Force reload to update template directory paths cache
class SimulatorView(View):
    """
    上位机模拟器页面视图
    """
    def get(self, request):
        return render(request, 'simulator/index.html')
