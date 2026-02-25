class SystemState:
    def __init__(self):
        self.reset_all() 
    def reset_all(self):
       
        self.reset = False         
        self.box_count = 0         
        self.box_wait = False
        
        self.rc_car_ready = False
        self.rc_car_id = None
        self.parking_done = False
        self.destination = None  

        print("val_reset_success")

    def one_cycle(self):
             
        self.box_count -= 1    
        self.box_wait = False
        self.rc_car_ready = False
        self.rc_car_id = None
        self.parking_done = False
        self.destination = None  