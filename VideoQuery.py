import tkinter as tk
import json
import sys
import os
from typing import NoReturn
from PIL import Image
from PIL.ImageTk import PhotoImage
import numpy as np
from tqdm import tqdm
import cv2
from scenedetect import VideoManager
from scenedetect import SceneManager
from scenedetect.detectors import ContentDetector
import face_recognition as fr

WIDTH, HEIGHT = 640, 360
VID_LEN, FPS = 20, 24
K = 1  # search parameter for search area
B_SIZE = 20  # size of macroblocks


def read_image_RGB(fp: str) -> np.ndarray:
    binary_file = np.fromfile(fp, dtype='uint8')
    N = WIDTH * HEIGHT  # num of pixels in the image
    
    # store rgbs values into a 3-D array to be used for Image.fromarray()
    rgbs = np.zeros((HEIGHT, WIDTH, 3), dtype='uint8')
    for i in range(3):
        rgbs[:, :, i] = np.frombuffer(binary_file[i*N:(i+1)*N],
                                      dtype='uint8').reshape((-1, WIDTH))
    return rgbs

def scene_detect(name: str, threshold: float = 30.0) -> int:
    video_manager = VideoManager([f'output_video/{name}.avi'])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    base_timecode = video_manager.get_base_timecode()
    video_manager.set_downscale_factor()
    print(f'\nDetecting scenes in video "{name}"...')
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list(base_timecode)
    return len(scene_list)-1

def face_detect(img_path: str) -> int:
    return len(fr.face_locations(fr.load_image_file(img_path)))


class VideoQuery:
    
    def __init__(self, fp: str):
        name = fp.split(os.sep)[-1]  # extract video name from file path
        category = name.split('_')[0]  # extract category from file path
        self.name = name
        self.category = category
        self.fp = fp
        # file paths to all frames
        dirs = sorted(os.listdir(self.fp), key=lambda x: int(x[5:-4]))
        fpaths = [f'{self.fp}/{frame}' for frame in dirs[:VID_LEN * FPS]]
        # read in all frames' rgb values
        print(f'\nReading RGB values of video "{self.name}"...')
        self.data = np.array([read_image_RGB(fp) for fp in tqdm(fpaths)])
        
    def calc_motion(self) -> int:
        # recast datatype to avoid over/underflow
        self.data = self.data.astype('int64')
        total_motion = 0
        print(f'Calculating motion of video "{self.name}"...')
        with tqdm(total=VID_LEN * FPS - 1) as bar:
            for frame_idx in range(VID_LEN * FPS - 1):
                for y in range(0, HEIGHT, B_SIZE):
                    for x in range(0, WIDTH, B_SIZE):
                        # for each block, find the search area with k
                        start_x, start_y = max(0, x - K), max(0, y - K)
                        end_x, end_y = min(WIDTH - B_SIZE, x + K), \
                                       min(HEIGHT - B_SIZE, y + K)
                        # calculate SAD for each target macro-block and compare
                        # it with the current macro-block to find the best match
                        min_SAD = np.inf
                        best_match = (0, 0)
                        for i in range(start_y, end_y + 1):
                            for j in range(start_x, end_x + 1):
                                sad = self.calc_SAD(frame_idx, i, j, y, x)
                                if sad < min_SAD:
                                    min_SAD = sad
                                    best_match = (i, j)
                        if best_match != (y, x):
                            total_motion += 1
                bar.update(1)
        return total_motion
    
    def calc_SAD(self, frame_idx: int,
                 c_y: int, c_x: int, n_y: int, n_x: int) -> np.ndarray:
        """
        :param frame_idx: frame index
        :param c_y: current frame Y-coordinate
        :param c_x: current frame X-coordinate
        :param n_y: next frame Y-coordinate
        :param n_x: next frame X-coordinate
        :return: The SAD of Y-values of the macro-block and its co-located
            macro-block in the next frame
        """
        curr_RGB = self.data[frame_idx, c_y:c_y + B_SIZE, c_x:c_x + B_SIZE]
        # curr_YUV = np.apply_along_axis(RGB_to_YUV, 2, curr_RGB)
        next_RGB = self.data[frame_idx + 1, n_y:n_y + B_SIZE, n_x:n_x + B_SIZE]
        # next_YUV = np.apply_along_axis(RGB_to_YUV, 2, next_RGB)
        diff = next_RGB - curr_RGB
        # diff = next_YUV - curr_YUV
        return np.sum(np.abs(diff))
    
    def detect_faces(self) -> float:
        jpg_path = self.fp.replace('_rgb/', '_jpg/')
        jpg_dirs = sorted(os.listdir(jpg_path), key= lambda x: int(x[5:-4]))
        jpg_paths = [f'{jpg_path}/{frame}' for frame in jpg_dirs[:VID_LEN*FPS]]
        print(f'\nDetecting faces in video {self.name}...')
        total_faces = sum(face_detect(jpg) for jpg in tqdm(jpg_paths))
        return total_faces / len(jpg_paths)
    
    def to_video(self) -> NoReturn:
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        vid_writer = cv2.VideoWriter(f'output_video/{self.name}.avi', fourcc,
                                     FPS, (WIDTH, HEIGHT))
        print(f'Converting "{self.name}" to .avi videos...')
        for frame in self.data:
            vid_writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        return
    
    def show_video(self) -> NoReturn:
        
        def update(ind: int) -> NoReturn:
            # the callback function to automatically update frames
            frame = frames[ind]  # get the frame at index
            ind += 1  # increment frame index
            if ind == VID_LEN * FPS:  # close GUI if reached end of the video
                # comment out if you want the video to persist after playing 20s
                root.destroy()
                return
            label.configure(image=frame)  # display frame
            root.after(40, update, ind)  # call to display next frame
            
        root = tk.Tk()
        label = tk.Label(root)
        # convert rgb values to PhotoImage for display in GUI
        #   when you add a PhotoImage to a Tkinter widget, you must keep your
        #   own reference to the image object, hence storing them in a list
        frames = [PhotoImage(Image.fromarray(d)) for d in self.data]
        label.pack()
        root.after(0, update, 0)
        root.mainloop()
        
        
if __name__ == '__main__':
    args = sys.argv
    if len(args) > 1:  # if input video specified, process single video
        fq = args[1]
        vid_name = fq.split('/')[-1]
        vq = VideoQuery(fq)
        faces = vq.detect_faces()
        print(faces)
        
        sys.exit()
    fpath = "/Users/yingxuanguo/Documents/USC/CSCI-576/Final Project/Test_rgb"
    categories = next(os.walk(fpath))[1]
    cat_paths = [os.path.join(fpath, cat) for cat in categories]
    vid_names = [next(os.walk(cat))[1] for cat in cat_paths]
    vid_paths = [[os.path.join(cat_paths[i], v) for v in cat]
                 for i, cat in enumerate(vid_names)]
    videos = [[VideoQuery(vid) for vid in cat] for cat in vid_paths]
    faces = {categories[i]:
                 {vid_names[i][j]: vid.detect_faces()
                  for j, vid in enumerate(c)}
             for i, c in enumerate(videos)}
    faces = {"feature_name": "avg_faces", "values": faces}
    with open('data.json', 'w') as f:
        json.dump(faces, f, indent=2, sort_keys=True)
