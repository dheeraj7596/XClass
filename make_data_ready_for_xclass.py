import pickle
import os

if __name__ == "__main__":
    pkl_dump_dir = "/Users/dheerajmekala/Work/WsupLD/data/agnews/"
    dataset = "agnews/"
    xclass_dump_dir = "/Users/dheerajmekala/Work/XClass/data/datasets/" + dataset
    os.makedirs(xclass_dump_dir, exist_ok=True)

    df = pickle.load(open(pkl_dump_dir + "df.pkl", "rb"))
    # parent_to_child = pickle.load(open(pkl_dump_dir + "parent_to_child.pkl", "rb"))
    classes = list(set(df["label"]))
    # df = df[df.label.isin(classes)].reset_index(drop=True)

    f1 = open(xclass_dump_dir + "classes.txt", "w")
    f2 = open(xclass_dump_dir + "labels.txt", "w")
    f3 = open(xclass_dump_dir + "dataset.txt", "w")

    label_to_idx = {}
    for i, l in enumerate(classes):
        label_to_idx[l] = i
        f1.write(l + "\n")

    for i, row in df.iterrows():
        f2.write(str(label_to_idx[row["label"]]) + "\n")
        f3.write(row["text"] + "\n")

    f1.close()
    f2.close()
    f3.close()
