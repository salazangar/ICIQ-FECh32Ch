# -*- coding: utf-8 -*-
"""Awooga.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1yp6qXBe5644XhCoTsEvQYYOMXv5RxiRw
"""

import torch
import os
import pandas as pd
from sklearn import preprocessing
from einops import rearrange

class HRRRComputedDataset(torch.utils.data.Dataset):

    def __init__(self, base_dir, data_info, column_names=None):
        """
        Dataset for the HRRR Computed Dataset

        :param base_dir: the root directory for the dataset
        :param data_info: a list of dictionaries containing information about the dataset
        :param column_names: a list of column names for the weather parameters
        """

        self.base_dir = base_dir
        self.data_info = data_info
        self.column_names = column_names

        # Define the default weather parameters if not provided
        if column_names is None:
            self.column_names = [
                'Avg Temperature (K)', 'Max Temperature (K)', 'Min Temperature (K)',
                'Precipitation (kg m**-2)', 'Relative Humidity (%)', 'Wind Gust (m s**-1)',
                'Wind Speed (m s**-1)', 'Downward Shortwave Radiation Flux (W m**-2)',
                'Vapor Pressure Deficit (kPa)'
            ]

        # only consider the first 28 days for addressing different days in each month
        self.day_range = [i + 1 for i in range(28)]

    def __len__(self):
        return len(self.data_info)

    def __getitem__(self, index):
        info = self.data_info[index]
        fips_code = info["FIPS"]
        year = info["year"]

        short_term_file_paths = [os.path.join(self.base_dir, path) for path in info["short_term"]]
        x_short = self.get_short_term_val(fips_code, short_term_file_paths)

        long_term_file_paths = [[os.path.join(self.base_dir, path) for path in paths] for paths in info["long_term"]]
        x_long = self.get_long_term_val(fips_code, long_term_file_paths)

        # Convert type
        x_short = x_short.to(torch.float32)
        x_long = x_long.to(torch.float32)

        return x_short, x_long, fips_code, year

    def get_short_term_val(self, fips_code, file_paths):
        """
        Return the daily weather parameters
        :param fips_code: the unique FIPS code for the county
        :param file_paths: the file paths for CSV files
        :return: short term weather data
        """
        df_list = []
        for file_path in file_paths:
            tmp_df = pd.read_csv(file_path)
            df_list.append(tmp_df)

        df = pd.concat(df_list, ignore_index=True)

        # Read FIPS code as string with leading zero
        df["FIPS Code"] = df["FIPS Code"].astype(str).str.zfill(5)

        # Filter the county and daily variables
        df = df[(df["FIPS Code"] == fips_code) & (df["Daily/Monthly"] == "Daily")]
        df.columns = df.columns.str.strip()

        group_month = df.groupby(['Month'])

        temporal_list = []
        for month, df_month in group_month:
            group_grid = df_month.groupby(['Grid Index'])

            time_series = []
            for grid, df_grid in group_grid:
                df_grid = df_grid.sort_values(by=['Day'], ascending=[True], na_position='first')

                df_grid = df_grid[df_grid.Day.isin(self.day_range)]
                df_grid = df_grid[self.column_names]
                val = torch.from_numpy(df_grid.values)
                time_series.append(val)

            temporal_list.append(torch.stack(time_series))

        x_short = torch.stack(temporal_list)
        #  m, d, g, and p represent the numbers of month, days, grids and parameters
        x_short = rearrange(x_short, 'm g d p -> m d g p')
        return x_short

    def get_long_term_val(self, fips_code, temporal_file_paths):
        """
        Return the monthly weather parameters
        :param fips_code: the unique FIPS code for the county
        :param temporal_file_paths: the file paths for CSV files
        :return: long term weather data
        """
        temporal_list = []

        for file_paths in temporal_file_paths:
            df_list = []
            for file_path in file_paths:
                tmp_df = pd.read_csv(file_path)
                df_list.append(tmp_df)

            df = pd.concat(df_list, ignore_index=True)

            # Read FIPS code as string with leading zero
            df["FIPS Code"] = df["FIPS Code"].astype(str).str.zfill(5)

            # Filter the county and daily variables
            df = df[(df["FIPS Code"] == fips_code) & (df["Daily/Monthly"] == "Monthly")]

            df.columns = df.columns.str.strip()
            group_month = df.groupby(['Month'])

            month_list = []
            for month, df_month in group_month:
                df_month = df_month[self.column_names]
                val = torch.from_numpy(df_month.values)
                val = torch.flatten(val, start_dim=0)
                month_list.append(val)

            temporal_list.append(torch.stack(month_list))

        x_long = torch.stack(temporal_list)
        return x_long

import h5py
import torch
import os
import numpy as np

class Sentinel2Imagery(torch.utils.data.Dataset):

    def __init__(self, base_dir, data_info, transform=None):
        """
        Dataset for Sentinel-2 Imagery

        :param base_dir: the root directory for the dataset
        :param data_info: a list of dictionaries containing information about the dataset
        :param transform: optional transform to be applied to the data
        """
        self.base_dir = base_dir
        self.data_info = data_info
        self.transform = transform

    def __len__(self):
        return len(self.data_info)

    def __getitem__(self, index):
        info = self.data_info[index]
        fips_code = info["FIPS"]
        year = info["year"]
        file_paths = [os.path.join(self.base_dir, path) for path in info["data_paths"]]

        temporal_list = []

        for file_path in file_paths:
            with h5py.File(file_path, 'r') as hf:
                groups = hf[fips_code]
                for d in groups.keys():
                    grids = groups[d]["data"]
                    grids = torch.from_numpy(np.asarray(grids))
                    temporal_list.append(grids)

        x = torch.stack(temporal_list)
        x = x.to(torch.float32)
        x = rearrange(x, 't g h w c -> t g c h w')

        if self.transform:
            t, g, _, _, _ = x.shape
            x = rearrange(x, 't g c h w -> (t g) c h w')
            x = self.transform(x)
            x = rearrange(x, '(t g) c h w -> t g c h w', t=t, g=g)

        return x, fips_code, year

import torch
from torch.utils.data import Dataset
import os
import pandas as pd

class USDACropDataset(torch.utils.data.Dataset):

    def __init__(self, base_dir, crop_type="Soybeans"):
        """
        Dataset for the USDA Crop Dataset

        :param base_dir: the root directory for CropNet dataset, e.g., /mnt/data/CropNet
        :param crop_type: the crop type for use. Choices: ["Corn", "Cotton", "Soybeans", "Winter Wheat"]
        """

        all_crop_types = ["Corn", "Cotton", "Soybeans", "Winter Wheat"]

        # validate the crop type
        assert crop_type in all_crop_types, f"Cannot find a crop type named {crop_type} in the USDA Crop Dataset."

        self.crop_type = crop_type

        if crop_type == "Cotton":
            column_names = ['PRODUCTION, MEASURED IN 480 LB BALES', 'YIELD, MEASURED IN BU / ACRE']
        else:
            column_names = ['PRODUCTION, MEASURED IN BU', 'YIELD, MEASURED IN BU / ACRE']

        self.column_names = column_names

        self.data = []

        # Define your dataset loading logic here
        data_dir = os.path.join(base_dir, "usda_data")  # Adjust based on your dataset structure

        # Example: walking through directories to find data files
        for root, dirs, files in os.walk(data_dir):
            for file in files:
                # Example: parsing filenames to extract metadata
                filename = os.path.splitext(file)[0]
                parts = filename.split("_")
                fips_code = parts[0]
                year = parts[1]
                state_ansi = parts[2]
                county_ansi = parts[3]

                file_path = os.path.join(root, file)
                df = pd.read_csv(file_path)

                # convert state_ansi and county_ansi to string with leading zeros
                df['state_ansi'] = df['state_ansi'].astype(str).str.zfill(2)
                df['county_ansi'] = df['county_ansi'].astype(str).str.zfill(3)

                df = df[(df["state_ansi"] == state_ansi) & (df["county_ansi"] == county_ansi)]

                df = df[self.column_names]

                x = torch.from_numpy(df.values)
                x = x.to(torch.float32)
                x = torch.log(torch.flatten(x, start_dim=0))

                self.data.append((x, fips_code, year))

    def __len__(self):
        return len(self.data)

    def __getitem__(self, index):
        return self.data[index]

# Import necessary libraries
import torch
from torch.utils.data import DataLoader
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score

# Assuming you have defined and instantiated your dataset classes properly

# Define the batch size and other parameters
batch_size = 32
num_workers = 2

# Instantiate your datasets
sentinel_dataset = Sentinel2Imagery(base_dir='/content/drive/MyDrive/CropNet/Sentinel-2 Imagery/data', data_info=data_info_sentinel, transform=None)
crop_dataset = USDACropDataset(base_dir='/content/drive/MyDrive/CropNet/USDA Crop Dataset/data', crop_type='Soybeans')
hrrr_dataset = HRRRComputedDataset(base_dir='/content/drive/MyDrive/CropNet/WRF-HRRR Computed Dataset/data', data_info=data_info_hrrr, column_names=None)

# Create DataLoader for each dataset
sentinel_loader = DataLoader(sentinel_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
crop_loader = DataLoader(crop_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
hrrr_loader = DataLoader(hrrr_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)

# Define empty lists to store features and labels
combined_X = []
combined_y = []

# Iterate over the loaders and combine the features and labels
for sentinel_data, crop_data, hrrr_data in zip(sentinel_loader, crop_loader, hrrr_loader):
    X_sentinel, _, _ = sentinel_data
    X_crop, _, _ = crop_data
    X_hrrr, _, _, _ = hrrr_data

    # Ensure that the shapes are compatible for concatenation
    # Here, you might need to apply transformations or adjustments
    # to make sure the shapes are compatible

    # Combine the features
    combined_features = torch.cat((X_sentinel, X_crop, X_hrrr), dim=1)
    combined_X.append(combined_features)

# Concatenate features and labels
combined_X = torch.cat(combined_X, dim=0)

# Assuming you have labels for the combined dataset
# Adjust this part according to your actual data structure
# Here, y_combined should be a tensor containing the labels for the combined dataset
# Make sure the shape and type of y_combined match the labels' format
# For demonstration purposes, let's assume y_combined is randomly generated
# You should replace this with your actual labels
y_combined = torch.randint(0, 2, (len(combined_X),), dtype=torch.long)

# Split the data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(combined_X, y_combined, test_size=0.2, random_state=42)

# Initialize SVM classifier
svm_classifier = SVC(kernel='linear', C=1.0)

# Train the SVM classifier
svm_classifier.fit(X_train, y_train)

# Predict on the test set
y_pred = svm_classifier.predict(X_test)

# Calculate accuracy
accuracy = accuracy_score(y_test, y_pred)
print("Accuracy:", accuracy)

import torch
from torch.utils.data import DataLoader
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC
from sklearn.metrics import accuracy_score

# Assuming you have defined and instantiated your dataset classes properly

# Define the batch size and other parameters
batch_size = 32
num_workers = 2

# Instantiate your datasets
sentinel_dataset = Sentinel2Imagery(base_dir='/content/drive/MyDrive/CropNet/Sentinel-2 Imagery/data', data_info=data_info_sentinel, transform=None)
crop_dataset = USDACropDataset(base_dir='/content/drive/MyDrive/CropNet/USDA Crop Dataset/data', data_info=data_info_crop, crop_type='Soybeans')
hrrr_dataset = HRRRComputedDataset(base_dir='/content/drive/MyDrive/CropNet/WRF-HRRR Computed Dataset/data', data_info=data_info_hrrr, column_names=None)

# Create DataLoader for each dataset
sentinel_loader = DataLoader(sentinel_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
crop_loader = DataLoader(crop_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)
hrrr_loader = DataLoader(hrrr_dataset, batch_size=batch_size, shuffle=True, num_workers=num_workers)

# Define empty lists to store features and labels
combined_X = []
combined_y = []

# Iterate over the loaders and combine the features and labels
for sentinel_data, crop_data, hrrr_data in zip(sentinel_loader, crop_loader, hrrr_loader):
    X_sentinel, _, _ = sentinel_data
    X_crop, _, _ = crop_data
    X_hrrr, _, _, _ = hrrr_data

    # Combine the features
    combined_features = torch.cat((X_sentinel, X_crop, X_hrrr), dim=1)
    combined_X.append(combined_features)

# Concatenate features and labels
combined_X = torch.cat(combined_X, dim=0)

# Assuming you have labels for the combined dataset
# Adjust this part according to your actual data structure
# Here, y_combined should be a tensor containing the labels for the combined dataset
# Make sure the shape and type of y_combined match the labels' format
# For demonstration purposes, let's assume y_combined is randomly generated
# You should replace this with your actual labels
y_combined = torch.randint(0, 2, (len(combined_X),), dtype=torch.long)

# Split the data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(combined_X, y_combined, test_size=0.2, random_state=42)

# Initialize SVM classifier
svm_classifier = SVC(kernel='linear', C=1.0)

# Train the SVM classifier
svm_classifier.fit(X_train, y_train)

# Predict on the test set
y_pred = svm_classifier.predict(X_test)

# Calculate accuracy
accuracy = accuracy_score(y_test, y_pred)
print("Accuracy:", accuracy)